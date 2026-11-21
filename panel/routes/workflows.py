"""The workflows saved in ComfyUI as each side lists them, what the panel made of them, their guides, and the workflow a run ran."""
import json
import os
import requests

from flask import Blueprint, abort, request

from panel import server

bp = Blueprint("workflows", __name__)


def _shown(value):
    """An input as the workflow viewer says it: a link to another node's output, or the value itself, cut if long."""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
        return f"→ node {value[0]}" + (f" (output {value[1]})" if value[1] else "")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 400 else text[:400] + "…"


@bp.route("/api/run-workflow")
@server.password_required
def run_workflow():
    """
    The workflow the current or last run renders with, as it is sent to ComfyUI with that run's options: which options
    were set, and every node with what it is given. For the page's Workflow view.
    """
    started = server.job.workflow
    if not started:
        return {"error": "Nothing has run yet."}, 404
    path, chosen, pipeline = started.get("path"), started.get("options") or {}, started.get("pipeline")
    if not path and pipeline == "video":
        path = server.video_comfy.DEFAULT_WORKFLOW
    if not path:
        return {"error": "This run uses the built-in workflow, which isn't a saved one."}, 404
    api = None
    if chosen:
        try:
            api = server.workflow_options.remake(path, chosen, pipeline)[0]
        except RuntimeError:
            api = None
    if api is None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                api = json.load(f)
        except (OSError, ValueError):
            return {"error": "That workflow's file is gone."}, 404
    try:
        with open(os.path.splitext(path)[0] + ".map.json", "r", encoding="utf-8") as f:
            offered = json.load(f).get("_options") or []
    except (OSError, ValueError):
        offered = []
    options = [{"label": option["label"], "value": chosen.get(option["id"], option["default"]), "changed": option["id"] in chosen}
               for option in offered if not option.get("role")]
    nodes = [{"id": node_id, "type": node.get("class_type", ""), "inputs": {name: _shown(value) for name, value in node.get("inputs", {}).items()}}
             for node_id, node in sorted(api.items(), key=lambda item: (not item[0].isdigit(), int(item[0]) if item[0].isdigit() else 0, item[0]))]
    return {"name": server.display_label(os.path.basename(path)), "pipeline": pipeline, "options": options, "nodes": nodes,
            "running": server.job.running, "api": api}


@bp.route("/api/workflows")
@server.password_required
def workflows():
    """
    What runs on this pipeline. logs/workflows/not_listed.json says why anything else isn't here.
    Image also lists what can't run, with why: it has no built-in workflow to fall back on, so an empty list says nothing.
    """
    pipeline = request.args.get("pipeline") or "video"
    found = [{key: w[key] for key in ("name", "label", "takes", "problem", "family") if w.get(key)} for w in server.saved_workflows()
             if w.get("pipeline", server.pipeline_of(w["name"])) == pipeline and (pipeline == "image" or "problem" not in w)]
    # The image_, video_ or shorts_ in front only sorts them in ComfyUI: here the side already says it.
    for w in found:
        w["label"] = server.display_label(w["label"])
        # The model family it runs (core/model_families.py): what its default preset and family default go by.
        if w.get("family"):
            w["family_label"] = server.model_families.family_label(w["family"])
    paths_by_name = {w["name"]: w.get("path") for w in server.saved_workflows()}
    for w in found:
        guide = server.model_guide.entry(server.model_guide.key_for_path(paths_by_name.get(w["name"]), pipeline))
        if guide:
            w["guide"] = guide
    if pipeline == "video":
        # How long its video model makes a clip, for the form to say.
        paths = {w["name"]: w.get("path") for w in server.saved_workflows()}
        for w in found:
            model = server.workflow_model(paths.get(w["name"]))
            w["clip_seconds"] = server.video_planner.clip_seconds(model)
            from core import h3_refiner
            from pipelines.video import h3_multishot
            from core import director
            w["openh3"] = h3_refiner.supports_path(paths.get(w["name"]))
            w["h3_multishot"] = h3_multishot.supports_path(paths.get(w["name"]))
            try:
                with open(paths.get(w["name"]) or "", encoding="utf-8") as file:
                    graph = json.load(file)
                w["h3_director"] = (director.INPUTS_ID in graph and
                                     graph[director.INPUTS_ID].get("class_type") == director.INPUTS)
            except (OSError, ValueError, AttributeError):
                w["h3_director"] = False
            if server.video_media.most_pixels(model):
                w["most_pixels"] = server.video_media.most_pixels(model)
    elif pipeline == "shorts":
        paths = {w["name"]: w.get("path") for w in server.saved_workflows()}
        for w in found:
            w["openh3"] = server.workflow_model(paths.get(w["name"])) == "minimax_h3"
    return {"online": server.comfyui_online(), "workflows": found, "built_in_guide": server.model_guide.entry(server.model_guide.BUILT_IN.get(pipeline))}


@bp.route("/api/workflow-check")
@server.password_required
def workflow_check():
    """
    What the panel made of every workflow saved in ComfyUI, for Settings' Workflows: see saved_workflows.report(). With
    refresh=1, read again from ComfyUI now, with the model families it can load (model_families.available()).
    """
    fresh = request.args.get("refresh") == "1"
    found = {"ok": True, "online": server.comfyui_online(), "workflows": server.saved_workflow_report(server.saved_workflows(fresh=fresh)), "tags": server.tag_help()}
    if fresh and found["online"]:
        try:
            found["families"] = server.model_families.available(server.comfyui_url())
        except (requests.RequestException, ValueError) as e:
            found["families_problem"] = f"Couldn't ask ComfyUI which models it can load: {e}"
    return found


@bp.route("/api/model-guide/<key>")
@server.password_required
def api_model_guide(key):
    """The guide to one diffusion model, for the link under the workflow picker."""
    found = server.model_guide.guide(key)
    if not found:
        abort(404)
    return {"ok": True, "guide": found}


server.app.register_blueprint(bp)
