"""Presets: a side's settings under a name, a workflow's own default, a model family's default."""
import json
import os

from flask import Blueprint, request

from panel import server

bp = Blueprint("presets", __name__)


PRESETS_PATH = os.path.join(server.LOGS_DIR, "presets.json")
PRESET_SIDES = ("shorts", "video", "image")
MOST_PRESET_NAME = 60


def load_presets():
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return {side: [p for p in saved.get(side, []) if isinstance(p, dict) and p.get("name")] for side in PRESET_SIDES}
    except (OSError, ValueError, AttributeError):
        return {side: [] for side in PRESET_SIDES}


# What a preset can be besides its settings, each held by one preset at most: the side's favourite (default, applied as the
# page opens), a workflow's own default (workflow_default: the workflow's name, applied when it's chosen), and its model
# family's default (family_default: core/model_families.py's id, applied to a workflow of it with no default of its own).
PRESET_FLAGS = ("default", "workflow_default", "family_default")
MOST_PRESET_KEY = 200


def _preset_key(value):
    """A workflow's or family's name as a flag holds it, or None for one that can't be."""
    return value.strip()[:MOST_PRESET_KEY] if isinstance(value, str) and value.strip() else None


def _set_preset_flag(presets, name, flag, value):
    """
    Gives the preset of this name the flag, or takes it away (value false or empty), taking it from whichever other
    preset held it: the favourite from any, a workflow's or family's default from the one for the same one. Returns a
    problem, or None.
    """
    if flag == "default":
        value = bool(value)
    elif value:
        value = _preset_key(value)
        if not value:
            return f"{flag.replace('_', ' ').capitalize()} must be a name."
    for p in presets:
        if p["name"] == name:
            continue
        if flag == "default" and value or p.get(flag) == value:
            p.pop(flag, None)
    for p in presets:
        if p["name"] == name:
            if value:
                p[flag] = value
            else:
                p.pop(flag, None)
    return None


@bp.route("/api/presets", methods=["GET", "POST"])
@server.password_required
def presets():
    """
    A side's settings under a name: kept here, so every device has the same ones. POST saves one (with workflow_default,
    as that workflow's own), deletes it, or gives it a flag (PRESET_FLAGS): {side, name, default | workflow_default |
    family_default}.
    """
    if request.method == "GET":
        return {"ok": True, "presets": load_presets()}
    body = request.get_json(silent=True) or {}
    side, name = body.get("side"), str(body.get("name") or "").strip()[:MOST_PRESET_NAME]
    if side not in PRESET_SIDES or not name:
        return {"ok": False, "error": "A preset needs a side and a name."}, 400
    saved = load_presets()
    flag = next((key for key in PRESET_FLAGS if key in body), None)
    if flag and "values" not in body and not body.get("delete"):
        if not any(p["name"] == name for p in saved[side]):
            return {"ok": False, "error": "There is no preset of that name."}, 404
        problem = _set_preset_flag(saved[side], name, flag, body[flag])
        if problem:
            return {"ok": False, "error": problem}, 400
    else:
        old = next((p for p in saved[side] if p["name"] == name), {})
        kept = [p for p in saved[side] if p["name"] != name]
        if not body.get("delete"):
            values = body.get("values")
            if not isinstance(values, dict):
                return {"ok": False, "error": "A preset needs its settings."}, 400
            workflow = body.get("workflow_default", old.get("workflow_default"))
            if workflow is not None and not _preset_key(workflow):
                return {"ok": False, "error": "A workflow default needs the workflow's name."}, 400
            # Saved over, it stays what it was: the side's favourite, a workflow's default, a family's default.
            kept.append({"name": name, "values": {str(k): v for k, v in values.items() if isinstance(v, (str, bool, int, float))},
                         **{key: old[key] for key in PRESET_FLAGS if old.get(key)}})
            if workflow:
                _set_preset_flag(kept, name, "workflow_default", workflow)
        saved[side] = sorted(kept, key=lambda p: p["name"].casefold())
    try:
        os.makedirs(os.path.dirname(PRESETS_PATH), exist_ok=True)
        with open(PRESETS_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False, indent=1)
        os.replace(PRESETS_PATH + ".tmp", PRESETS_PATH)
    except OSError as e:
        return {"ok": False, "error": f"Could not save it: {e}"}, 500
    return {"ok": True, "presets": saved}


server.app.register_blueprint(bp)
