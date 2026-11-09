"""The few settings the gear in the header holds, kept in logs/settings.json so every device sees the same."""
import json
import os
import threading

from core.paths import LOGS_DIR

PATH = os.path.join(LOGS_DIR, "settings.json")
SIDES = ("shorts", "video", "image")
MAX_RESERVE_GB = 64
H3_MODELS = ("gemma-4-12b", "qwen3-14b")
# local_llm_model writes the prompts when the local model is chosen; h3_model is OpenH3-IR's, which reviews and
# renders them. Apart, so one can be the vision model and the other the text one.
# Free RAM ComfyUI keeps, in GB: 3 unless set (0, from before, meant ComfyUI's own, which had no floor).
DEFAULT_RESERVE_GB = 3
DEFAULTS = {"low_priority": False, "reserve_ram_gb": DEFAULT_RESERVE_GB, "h3_model": H3_MODELS[0], "local_llm_model": H3_MODELS[0],
            "default_workflow": {side: "" for side in SIDES}}
_lock = threading.Lock()


def _gigabytes(value):
    """Whole or half gigabytes, 0 (ComfyUI's own default) up to MAX_RESERVE_GB; anything else is 0."""
    try:
        gb = float(value)
    except (TypeError, ValueError):
        return 0
    return round(min(max(gb, 0), MAX_RESERVE_GB) * 2) / 2 if gb == gb else 0


def _saved():
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    return saved if isinstance(saved, dict) else {}


def load():
    saved = _saved()
    workflows = saved.get("default_workflow") if isinstance(saved.get("default_workflow"), dict) else {}
    model = saved.get("h3_model", DEFAULTS["h3_model"])
    if model not in H3_MODELS:
        raise ValueError(f"Unknown OpenH3-IR model: {model!r}")
    # Before it had a setting of its own, the local model was OpenH3-IR's: kept so until it is chosen.
    local = saved.get("local_llm_model") or model
    return {"low_priority": bool(saved.get("low_priority")),
            "reserve_ram_gb": _gigabytes(saved.get("reserve_ram_gb")) or DEFAULT_RESERVE_GB,
            "h3_model": model,
            "local_llm_model": local if local in H3_MODELS else DEFAULTS["local_llm_model"],
            "default_workflow": {side: str(workflows.get(side) or "") for side in SIDES},
            # The image preset the viewer's Edit (pen) opens Generate with; empty: the Qwen-Image 2.1 edit workflow.
            "edit_preset": str(saved.get("edit_preset") or "")[:200],
            # Private mode: what is made is tagged NSFW, and Output opens on the NSFW filter. Kept over restarts.
            "private_mode": bool(saved.get("private_mode"))}


def update(changes):
    """Applies the settings in changes (the ones it knows, valid ones only) and returns them all."""
    with _lock:
        current = load()
        if "low_priority" in changes:
            current["low_priority"] = bool(changes["low_priority"])
        if "reserve_ram_gb" in changes:
            current["reserve_ram_gb"] = _gigabytes(changes["reserve_ram_gb"])
        if "h3_model" in changes:
            if changes["h3_model"] not in H3_MODELS:
                raise ValueError("Unknown OpenH3-IR model.")
            current["h3_model"] = changes["h3_model"]
        if "local_llm_model" in changes:
            if changes["local_llm_model"] not in H3_MODELS:
                raise ValueError("Unknown local LLM model.")
            current["local_llm_model"] = changes["local_llm_model"]
        if "private_mode" in changes:
            current["private_mode"] = bool(changes["private_mode"])
        if "edit_preset" in changes:
            current["edit_preset"] = str(changes["edit_preset"] or "")[:200]
        if isinstance(changes.get("default_workflow"), dict):
            for side in SIDES:
                if side in changes["default_workflow"]:
                    current["default_workflow"][side] = str(changes["default_workflow"][side] or "")
        # Never chosen, the local LLM's model follows OpenH3-IR's: saved only once it is chosen.
        if "local_llm_model" not in changes and not _saved().get("local_llm_model"):
            current.pop("local_llm_model")
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        return load()
