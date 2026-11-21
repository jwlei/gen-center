"""Write prompt: an LLM rewriting a rough idea into a detailed prompt, streamed as it writes."""
import json
import math
import os
import re
import secrets
import threading

from flask import Blueprint, Response, request

from panel import server

bp = Blueprint("prompt_writer", __name__)


def streamed_prompt(write):
    """
    write(on_text) run on a thread, the prompt sent to the page as it is written: a JSON object a line, {"text": piece}
    for each piece, then write's answer as it would have been ({"ok": true, "prompt": ...} or {"ok": false, ...}).
    """
    import queue as queue_module
    pieces = queue_module.Queue()

    def run():
        try:
            reply = write(pieces.put)
        except Exception as error:  # write answers what it expects itself: the page must still hear the end
            server.app.logger.exception("The prompt writer failed")
            reply = {"ok": False, "error": str(error)}
        pieces.put((reply[0] if isinstance(reply, tuple) else reply,))

    threading.Thread(target=run, daemon=True).start()

    def lines():
        while True:
            piece = pieces.get()
            if isinstance(piece, tuple):
                yield json.dumps(piece[0], ensure_ascii=False) + "\n"
                return
            yield json.dumps({"text": piece}, ensure_ascii=False) + "\n"

    response = Response(lines(), mimetype="application/x-ndjson")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@bp.route("/api/write-prompt", methods=["GET", "POST"])
@server.password_required
def write_prompt():
    from core import h3_refiner
    from google.genai.errors import APIError

    if request.method == "GET":
        side = request.args.get("pipeline")
        writer = request.args.get("writer") or "local"
        if side not in ("image", "video"):
            return {"ok": False, "error": "Choose an image or video prompt."}, 400
        if writer not in ("local", "gemini", "prompt_enhancer") or (writer == "prompt_enhancer" and side != "image"):
            return {"ok": False, "error": "Choose a prompt writer supported for this generation setup."}, 400
        if writer == "gemini" and not os.getenv("GEMINI_API_KEY"):
            return {"ok": False, "error": "Gemini has no API key in .env."}, 400
        try:
            model = (request.args.get("model") or h3_refiner.local_llm_model()) if writer == "local" else writer.replace("_", "-")
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 500
        if writer == "local" and model not in {item["id"] for item in server.settings.local_models()}:
            return {"ok": False, "error": "Choose a local prompt model available in Settings."}, 400
        timings = server.eta_keys.Timings(server.PROMPT_WRITER_TIMINGS, {})
        # Kept loaded, it skips the start: timed apart, the cold time standing in until it has been.
        cold = f"{model} | {side}"
        estimate = timings.step([cold + " | warm", cold] if writer == "local" and server.warm_model() == model else cold)
        if estimate is not None and (not math.isfinite(estimate) or estimate <= 0):
            server.app.logger.warning("Invalid prompt writer timing for %s / %s: %s", model, side, estimate)
            estimate = None
        default = (300 if server.settings.model_family(model) == "qwen3-14b" else 180) if writer == "local" else (180 if writer == "prompt-enhancer" else 45)
        return {"ok": True, "writer": writer, "model": model, "seconds": estimate if estimate is not None else default}
    data = request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(data, dict) or data.get("pipeline") not in ("image", "video"):
        return {"ok": False, "error": "Choose an image or video prompt."}, 400
    text = data.get("prompt")
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        return {"ok": False, "error": "Enter a prompt of up to 16,000 characters."}, 400
    writer = data.get("writer") or "local"
    side = data["pipeline"]
    if writer not in ("local", "gemini", "prompt_enhancer") or (writer == "prompt_enhancer" and side != "image"):
        return {"ok": False, "error": "Choose a prompt writer supported for this generation setup."}, 400
    if writer == "gemini" and not os.getenv("GEMINI_API_KEY"):
        return {"ok": False, "error": "Gemini has no API key in .env."}, 400
    if writer == "local":
        try:
            model = data.get("model") or h3_refiner.local_llm_model()
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 500
        if model not in {item["id"] for item in server.settings.local_models()}:
            return {"ok": False, "error": "Choose a local prompt model available in Settings."}, 400
    else:
        model = writer.replace("_", "-")
    with server.run_queue.lock:
        if server._writing_prompt or server._panel_closing or server._comfy_restarting or server._comfy_freeing or server.job.running or (server.run_queue.pending() and not server.run_queue.held):
            return {"ok": False, "error": "Wait for the current generation or prompt writer to finish."}, 409
        server._writing_prompt = True

    def write(on_text=None):
        """Writes it, the writer's turn over at the end however it went. on_text: each piece, as a local model writes it."""
        warm = False
        try:
            started = server.time.monotonic()
            if writer == "local":
                refiner = server.take_warm(model)
                warm = refiner is not None
                if warm:
                    # Something may have used ComfyUI since (its own page): it lets go of what it loaded again first.
                    try:
                        refiner._release_comfy_models()
                    except BaseException:
                        refiner.__exit__(None, None, None)
                        raise
                else:
                    url = server.comfyui_url()
                    # Writing from words alone: no vision projector, which leaves its memory to the model.
                    refiner = h3_refiner.Refiner(url, require_compiler=False, model_id=model, vision=False)
                    if refiner.model_id != model:
                        return {"ok": False, "error": "The selected model changed. Try writing the prompt again."}, 409
                with server.run_queue.lock:
                    server._prompt_refiner = refiner
                try:
                    if not warm:
                        refiner.__enter__()
                    prompt = refiner.write_prompt(text.strip(), side, **({"on_text": on_text} if on_text else {}))
                except BaseException:
                    refiner.__exit__(None, None, None)
                    raise
                server.keep_warm(refiner)
            elif writer == "gemini":
                from google.genai import types
                from core import gemini, prompt_writer_instructions
                response = gemini._generate(
                    text.strip(),
                    config=types.GenerateContentConfig(system_instruction=prompt_writer_instructions.INSTRUCTIONS[side]))
                prompt = getattr(response, "text", None)
                if not isinstance(prompt, str) or not prompt.strip():
                    raise RuntimeError("Gemini returned an empty prompt.")
                prompt = prompt.strip()
            else:
                # The workflow's enhancer runs in ComfyUI, which needs the memory a warm local model holds.
                server.close_warm_writer()
                from panel import image as image_panel
                from pipelines.image.comfy import ImageClient
                uploads = image_panel.form_uploads(request.files)
                env, takes, error = image_panel.chosen_workflow(request.form, len(uploads))
                if error:
                    return {"ok": False, "error": error}, 400
                enhancer = next((option for option in takes.get("options", []) if option.get("id") == "prompt_enhancer"), None)
                if not enhancer:
                    return {"ok": False, "error": "The selected image workflow has no prompt enhancer."}, 400
                if enhancer.get("problem"):
                    return {"ok": False, "error": f"{enhancer['label']} can't run: {enhancer['problem']}"}, 400
                from core import workflow_options
                takes = workflow_options.takes_for(takes, server.form_options(request.form, takes)[0])
                if not takes["min_images"] <= len(uploads) <= takes["max_images"]:
                    return {"ok": False, "error": "Choose the number of source images this workflow needs."}, 400
                workflow_path = env.get("COMFYUI_WORKFLOW")
                if not workflow_path:
                    return {"ok": False, "error": "Choose an image workflow with a prompt enhancer."}, 400
                options, error = server.form_options(request.form, takes)
                if error:
                    return {"ok": False, "error": error}, 400
                options["prompt_enhancer"] = "1"
                comfy = ImageClient(options, workflow_path=workflow_path)
                if not comfy.wait_until_reachable():
                    raise RuntimeError(f"ComfyUI isn't running at {comfy.url}. Start it first.")
                images = []
                for upload in uploads:
                    try:
                        server.video_media.load_image(upload.stream)
                    except RuntimeError:
                        return {"ok": False, "error": "That file isn't an image this can read."}, 400
                    upload.stream.seek(0)
                    extension = os.path.splitext(upload.filename)[1].lower()
                    extension = extension if re.fullmatch(r"\.[a-z0-9]{1,5}", extension) else ""
                    images.append(comfy._send_image(upload.stream, f"prompt-editor-{secrets.token_hex(8)}{extension}"))
                prompt = comfy.enhance(text.strip(), images)
                if not prompt or not prompt.strip():
                    raise RuntimeError("The workflow's prompt enhancer returned no text.")
            timings = server.eta_keys.Timings(server.PROMPT_WRITER_TIMINGS, {})
            key = f"{model} | {side}" + (" | warm" if warm else "")
            old = timings.timed_step(key)
            if old is not None and (not math.isfinite(old) or old <= 0):
                server.app.logger.warning("Discarding invalid prompt writer timing for %s: %s", key, old)
                timings.timed_steps.discard(key)
            timings.learn_step(key, server.time.monotonic() - started)
            try:
                os.makedirs(os.path.dirname(server.PROMPT_WRITER_TIMINGS), exist_ok=True)
                temporary = server.PROMPT_WRITER_TIMINGS + ".tmp"
                with open(temporary, "w", encoding="utf-8") as file:
                    json.dump(timings.as_dict(), file, indent=2)
                os.replace(temporary, server.PROMPT_WRITER_TIMINGS)
            except OSError as e:
                server.app.logger.warning("Could not save local prompt writer timings: %s", e)
            return {"ok": True, "prompt": prompt}
        except (RuntimeError, OSError, ValueError, APIError) as e:
            return {"ok": False, "error": str(e)}, 500
        finally:
            with server.run_queue.lock:
                server._writing_prompt = False
                server._prompt_refiner = None
            server.run_queue._advance_locked()

    # A local model's prompt shown as it is written (the editor asks for it): the writing goes on on a thread, so a
    # page that stops reading leaves it to finish, its model kept loaded, rather than cut off.
    if writer == "local" and str(data.get("stream") or "") == "1":
        return streamed_prompt(write)
    return write()


server.app.register_blueprint(bp)
