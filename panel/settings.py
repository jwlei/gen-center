"""The few settings the gear in the header holds, kept in logs/settings.json so every device sees the same."""
import json
import os
import threading

from core.paths import LOGS_DIR

PATH = os.path.join(LOGS_DIR, "settings.json")
SIDES = ("shorts", "video", "image")
MAX_RESERVE_GB = 64
H3_MODELS = ("gemma-4-12b", "qwen3-14b")
# Who titles a new film or set (core/titles.py): nobody, Gemini with the local model behind it, the local model alone,
# or Gemini for what isn't NSFW (made outside Private mode) and the local model for what is.
TITLE_SOURCES = ("off", "gemini", "gemini_sfw", "local")
# Name and the background, panel, raised panel, border, text, muted text and accent colours.
THEMES = {
    "standard": ("Standard", "#0e0f13", "#171922", "#1e212c", "#2a2e3c", "#e8eaf0", "#969cae", "#f2622e"),
    "nord": ("Nord", "#242933", "#2e3440", "#3b4252", "#4c566a", "#eceff4", "#a9b5c7", "#5e81ac"),
    "amoled": ("AMOLED Black", "#000000", "#0b0b0b", "#181818", "#303030", "#f3f3f3", "#a5a5a5", "#b94c29"),
    "solarized": ("Solarized Dark", "#00212b", "#002b36", "#073642", "#28515a", "#eee8d5", "#93a1a1", "#b06a08"),
    "dracula": ("Dracula", "#20212b", "#282a36", "#343746", "#45495b", "#f8f8f2", "#b4b8cb", "#9864bd"),
    "monokai": ("Monokai", "#1c1d19", "#272822", "#34352c", "#494a3d", "#f8f8f2", "#b2b1a3", "#aa563c"),
    "gruvbox": ("Gruvbox", "#1d2021", "#282828", "#3c3836", "#504945", "#ebdbb2", "#bdae93", "#b26025"),
    "tokyo-night": ("Tokyo Night", "#161824", "#1a1b26", "#24283b", "#3b4261", "#c0caf5", "#9aa5ce", "#5273c7"),
    "catppuccin": ("Catppuccin Mocha", "#11111b", "#1e1e2e", "#313244", "#45475a", "#cdd6f4", "#a6adc8", "#8d67bb"),
    "everforest": ("Everforest", "#202928", "#2d353b", "#374247", "#4a5759", "#d3c6aa", "#a7b49c", "#65825a"),
    "rose-pine": ("Rosé Pine", "#191724", "#1f1d2e", "#26233a", "#403d52", "#e0def4", "#a5a1b9", "#a45973"),
    "midnight": ("Midnight Blue", "#0a101e", "#101a2d", "#192640", "#2a3a57", "#e2eafa", "#9caec9", "#3966b2"),
    "forest": ("Deep Forest", "#0c1713", "#14231c", "#1c3025", "#324a39", "#e1eee2", "#a0b8a4", "#438457"),
    "plum": ("Plum", "#180e1a", "#251529", "#332039", "#4b3251", "#f2e5f1", "#c0a3be", "#a04f8e"),
    "ember": ("Ember", "#1a100d", "#281b16", "#38271f", "#513c30", "#f4e8db", "#c3a99a", "#b45c2f"),
    "slate": ("Slate", "#111518", "#1b2227", "#273137", "#3b4a51", "#e3ecec", "#a3b5b7", "#387f86"),
}
# local_llm_model writes the prompts when the local model is chosen; h3_model is OpenH3-IR's, which reviews and
# renders them. Apart, so one can be the vision model and the other the text one.
# Free RAM ComfyUI keeps, in GB: 3 unless set (0, from before, meant ComfyUI's own, which had no floor).
DEFAULT_RESERVE_GB = 3
DEFAULTS = {"low_priority": False, "reserve_ram_gb": DEFAULT_RESERVE_GB, "h3_model": H3_MODELS[0], "local_llm_model": H3_MODELS[0],
            "default_workflow": {side: "" for side in SIDES}, "title_source": "off", "pin_progress": False, "theme": "standard"}
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
    theme = saved.get("theme")
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
            # The video preset the viewer's Edit menu opens Video with, its image in image 1 (an image-to-video one).
            "edit_video_preset": str(saved.get("edit_video_preset") or "")[:200],
            # Private mode: what is made is tagged NSFW, and Output opens on the NSFW filter. Kept over restarts.
            "private_mode": bool(saved.get("private_mode")),
            # Titles: who titles a new film or set from its prompt (core/titles.py). Before it was a choice, Gemini titles
            # on meant "gemini".
            "title_source": saved["title_source"] if saved.get("title_source") in TITLE_SOURCES else "gemini" if saved.get("gemini_titles") else "off",
            # Pin the progress bar: scrolled away from the top, the header's progress bar stays, along the top of the screen.
            "pin_progress": bool(saved.get("pin_progress")),
            "theme": theme if isinstance(theme, str) and theme in THEMES else DEFAULTS["theme"]}


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
        if "title_source" in changes:
            if changes["title_source"] not in TITLE_SOURCES:
                raise ValueError("Unknown title source.")
            current["title_source"] = changes["title_source"]
        if "pin_progress" in changes:
            current["pin_progress"] = bool(changes["pin_progress"])
        if "theme" in changes:
            if not isinstance(changes["theme"], str) or changes["theme"] not in THEMES:
                raise ValueError("Unknown theme.")
            current["theme"] = changes["theme"]
        if "edit_preset" in changes:
            current["edit_preset"] = str(changes["edit_preset"] or "")[:200]
        if "edit_video_preset" in changes:
            current["edit_video_preset"] = str(changes["edit_video_preset"] or "")[:200]
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
