"""The few settings the gear in the header holds, kept in logs/settings.json so every device sees the same."""
import json
import logging
import math
import os
import re
import threading

from core.paths import LOGS_DIR, PROJECT_ROOT

PATH = os.path.join(LOGS_DIR, "settings.json")
SIDES = ("shorts", "video", "image")
MAX_RESERVE_GB = 64
H3_MODELS = ("gemma-4-12b", "qwen3-14b")
MODEL_FOLDERS = {"gemma-4-12b": "gemma-4-12b-heretic", "qwen3-14b": "qwen3-14b-abliterated"}
_logger = logging.getLogger(__name__)


def local_model_benchmarks():
    try:
        with open(os.path.join(LOGS_DIR, "local_model_benchmarks.json"), encoding="utf-8") as source:
            data = json.load(source)
        if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
            raise ValueError("Invalid benchmark data.")
        return data
    except FileNotFoundError:
        return {"models": {}}
    except (OSError, ValueError) as error:
        _logger.warning("Could not read local model benchmarks: %s", error)
        return {"models": {}}


def benchmark_for_model(benchmarks, model_id, model_path, server_path=None):
    result = benchmarks["models"].get(model_id)
    if not isinstance(result, dict):
        return None
    try:
        if (os.path.normcase(os.path.abspath(model_path)) != result["model_path"]
                or os.path.getmtime(model_path) != result["model_mtime"]):
            return None
        if server_path is not None and (
                os.path.normcase(os.path.abspath(server_path)) != result["server_path"]
                or os.path.getmtime(server_path) != result["server_mtime"]):
            return None
        layers = result["gpu_layers"]
        if layers != "all" and (not isinstance(layers, int) or isinstance(layers, bool) or layers < 0):
            raise ValueError("Invalid benchmark GPU layer count.")
        return result
    except (KeyError, OSError, TypeError, ValueError) as error:
        _logger.warning("Could not use local model benchmark for %s: %s", model_id, error)
        return None


def model_family(model_id):
    if not isinstance(model_id, str):
        raise ValueError("Unknown local model.")
    family, separator, folder = model_id.partition(":")
    if family not in H3_MODELS or (separator and (not folder or os.path.basename(folder) != folder
                                                    or "/" in folder or "\\" in folder or ":" in folder
                                                    or folder in (".", ".."))):
        raise ValueError(f"Unknown local model: {model_id!r}")
    return family


# A local model's name in a list, short enough to read: its family, the model's own name if it has one (Fable5), what
# was done to it in letters (QAT, U for uncensored, H for heretic, A for abliterated), and its quantisation:
# "Gemma 4 Fable5-U-H Q5_K_M". The built-in Gemma is named from its file; the built-in Qwen3 is just that.
FAMILY_NAMES = {"gemma-4-12b": "Gemma 4", "qwen3-14b": "Qwen3 14B"}
FAMILY_GROUPS = {"gemma-4-12b": "Gemma 4 12B · sees images", "qwen3-14b": "Qwen3 14B · text only"}
_QUANT = re.compile(r"[-_.](I?Q\d(?:_[A-Za-z0-9]+)+|BF16|F16)$", re.I)
_TAGS = (("qat", "QAT"), ("uncensored", "U"), ("heretic", "H"), ("abliterated", "A"))


def _model_file_stem(folder):
    """The name of a model folder's model file, without .gguf: what it is, where the folder's own name doesn't say."""
    try:
        with os.scandir(os.path.join(PROJECT_ROOT, "models", folder)) as entries:
            names = sorted(entry.name for entry in entries if entry.is_file() and entry.name.lower().endswith(".gguf")
                           and "mmproj" not in entry.name.lower())
    except OSError:
        return ""
    return names[0][:-len(".gguf")] if names else ""


def short_name(model_id, file_stem=None):
    """
    "gemma-4-12b:gemma-4-12B-it-qat-q4_0-unquantized-heretic-Q4_K_M" -> "Gemma 4 QAT-H Q4_K_M". file_stem: the built-in
    Gemma's model file name, found on disk when not given.
    """
    family, separator, folder = model_id.partition(":")
    name = FAMILY_NAMES.get(family, family)
    if not separator:
        if family != "gemma-4-12b":
            return name
        folder = file_stem if file_stem is not None else _model_file_stem(MODEL_FOLDERS[family])
        if not folder:
            return name
    quant = _QUANT.search(folder)
    words = [word.lower() for word in re.split(r"-+", folder[:quant.start()] if quant else folder) if word]
    # Its own name: the first word with a number in it that isn't a size, version or quantisation (fable5).
    own = next((word for word in words if re.search(r"[a-z]", word) and re.search(r"\d", word) and "." not in word
                and not re.fullmatch(r"\d+b|v\d+|q\d(_\w+)?|gemma|qwen\d*", word)), None)
    parts = ([own[:1].upper() + own[1:]] if own else []) + [tag for word, tag in _TAGS if word in words]
    return " ".join(part for part in [name, "-".join(parts), quant.group(1).upper() if quant else ""] if part)


def local_models():
    models = [{"id": "gemma-4-12b", "label": "Gemma 4 12B (vision)"},
              {"id": "qwen3-14b", "label": "Qwen3 14B (text only)"}]
    root = os.path.join(PROJECT_ROOT, "models")
    if os.path.isdir(root):
        with os.scandir(root) as entries:
            folders = sorted((entry for entry in entries if entry.is_dir(follow_symlinks=False)),
                             key=lambda entry: entry.name.casefold())
        for folder in folders:
            if folder.name.casefold() in {name.casefold() for name in MODEL_FOLDERS.values()}:
                continue
            if re.search(r"gemma[-_]?4[-_]?12b", folder.name, re.I):
                family = "gemma-4-12b"
            elif re.search(r"qwen3[-_]?14b", folder.name, re.I):
                family = "qwen3-14b"
            else:
                continue
            with os.scandir(folder.path) as entries:
                if not any(entry.is_file() and entry.name.lower().endswith(".gguf")
                           and "mmproj" not in entry.name.lower() for entry in entries):
                    continue
            models.append({"id": f"{family}:{folder.name}", "label": folder.name})
    rates = local_model_rates(models)
    for model in models:
        model["tokens_per_second"] = rates.get(model["id"])
        model["vision"] = model_family(model["id"]) == "gemma-4-12b"
        model["short"] = short_name(model["id"])
        model["group"] = FAMILY_GROUPS.get(model_family(model["id"]), "")
    return models


def local_model_rates(models):
    mtimes, paths = {}, {}
    for model in models:
        model_id = model["id"]
        folder = model_id.split(":", 1)[1] if ":" in model_id else MODEL_FOLDERS[model_id]
        directory = os.path.join(PROJECT_ROOT, "models", folder)
        override = os.getenv("H3IR_MODEL_FILE")
        try:
            if override:
                path = override
            else:
                with os.scandir(directory) as entries:
                    candidates = [entry.path for entry in entries if entry.is_file()
                                  and entry.name.lower().endswith(".gguf") and "mmproj" not in entry.name.lower()]
                if len(candidates) != 1:
                    continue
                path = candidates[0]
            mtimes[model_id] = os.path.getmtime(path)
            paths[model_id] = path
        except FileNotFoundError:
            continue
        except OSError as error:
            _logger.warning("Could not inspect local model for token statistics: %s", error)
    benchmarks = local_model_benchmarks()
    baseline = benchmarks.get("at", 0)
    if not isinstance(baseline, (int, float)) or isinstance(baseline, bool) or not math.isfinite(baseline):
        _logger.warning("Invalid local model benchmark timestamp.")
        baseline = 0
    active, totals = {}, {}
    for model_id, model_path in paths.items():
        result = benchmark_for_model(benchmarks, model_id, model_path)
        if result:
            tokens, milliseconds = result.get("tokens"), result.get("milliseconds")
            if (isinstance(tokens, (int, float)) and not isinstance(tokens, bool) and math.isfinite(tokens)
                    and isinstance(milliseconds, (int, float)) and not isinstance(milliseconds, bool)
                    and math.isfinite(milliseconds) and tokens > 0 and milliseconds > 0):
                totals[model_id] = (tokens, milliseconds)
    path = os.path.join(LOGS_DIR, "local_llm_tokens.jsonl")
    try:
        with open(path, encoding="utf-8") as source:
            for number, line in enumerate(source, 1):
                try:
                    event = json.loads(line)
                except ValueError:
                    _logger.warning("Could not read local token statistics at line %s", number)
                    continue
                if not isinstance(event, dict):
                    continue
                pid, model_id = event.get("pid"), event.get("model")
                if not isinstance(pid, int) or not isinstance(model_id, str):
                    continue
                if event.get("event") == "start":
                    active[pid] = (model_id, event.get("model_mtime"))
                elif (event.get("event") == "completion" and model_id in mtimes
                      and active.get(pid) == (model_id, mtimes[model_id])
                      and isinstance(event.get("at", 0), (int, float))
                      and event.get("at", 0) >= baseline):
                    timing = event.get("timings")
                    if not isinstance(timing, dict):
                        continue
                    tokens, milliseconds = timing.get("predicted_n"), timing.get("predicted_ms")
                    if (not isinstance(tokens, (int, float)) or isinstance(tokens, bool)
                            or not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool)
                            or not math.isfinite(tokens) or not math.isfinite(milliseconds)
                            or tokens <= 0 or milliseconds <= 0):
                        continue
                    old_tokens, old_ms = totals.get(model_id, (0, 0))
                    totals[model_id] = (old_tokens + tokens, old_ms + milliseconds)
    except FileNotFoundError:
        pass
    except OSError as error:
        _logger.warning("Could not read local token statistics: %s", error)
        return {}
    return {model_id: round(tokens * 1000 / milliseconds, 1)
            for model_id, (tokens, milliseconds) in totals.items()}


def model_folder(model_id):
    family = model_family(model_id)
    if ":" not in model_id:
        return MODEL_FOLDERS[family]
    if model_id not in {model["id"] for model in local_models()}:
        raise ValueError(f"The local model folder for {model_id!r} is missing or unsupported.")
    return model_id.split(":", 1)[1]
# Who titles a new film or set (core/titles.py): nobody, Gemini with the local model behind it, the local model alone,
# or Gemini for what isn't NSFW (made outside Private mode) and the local model for what is.
TITLE_SOURCES = ("off", "gemini", "gemini_sfw", "local")
# Name and the background, panel, raised panel, border, text, muted text and accent colours.
THEMES = {
    "standard": ("Standard", "#0e0f13", "#171922", "#1e212c", "#2a2e3c", "#e8eaf0", "#969cae", "#a07cff"),
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
            "default_workflow": {side: "" for side in SIDES}, "title_source": "off", "pin_progress": False,
            "top_progress": True, "status_progress": False, "theme": "standard", "theme_boxes": True,
            "page_swipe": True, "page_animation": "push", "page_speed": "normal"}
# A phone's swipe from one page to the next (Status, Generate, Output): on or off, how the page comes in, how quickly.
PAGE_ANIMATIONS = ("slide", "push", "fade", "zoom", "flip", "off")
PAGE_SPEEDS = ("slow", "normal", "fast")
_lock = threading.Lock()
# GPU heat guard (panel/gpu_guard.py): MSI Afterburner restarted above gpu_restart_above C, with profile gpu_profile,
# and again only once the GPU has cooled to gpu_rearm_at C.
GPU_GUARD_DEFAULTS = {"gpu_guard": True, "gpu_restart_above": 78, "gpu_rearm_at": 75, "gpu_profile": 3}
GPU_LOWEST_C, GPU_HIGHEST_C = 40, 95


def _names(value):
    """A list of workflow names, as saved: what isn't one is left out."""
    return [name for name in value if isinstance(name, str) and name.strip()][:100] if isinstance(value, list) else []


def _whole(value, low, high):
    """value as a whole number from low to high, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number == int(number) and low <= number <= high else None


def _gpu_guard(saved):
    above = _whole(saved.get("gpu_restart_above"), GPU_LOWEST_C, GPU_HIGHEST_C) or GPU_GUARD_DEFAULTS["gpu_restart_above"]
    rearm = _whole(saved.get("gpu_rearm_at"), GPU_LOWEST_C, GPU_HIGHEST_C) or GPU_GUARD_DEFAULTS["gpu_rearm_at"]
    if rearm >= above:
        above, rearm = GPU_GUARD_DEFAULTS["gpu_restart_above"], GPU_GUARD_DEFAULTS["gpu_rearm_at"]
    return {"gpu_guard": bool(saved.get("gpu_guard", True)), "gpu_restart_above": above, "gpu_rearm_at": rearm,
            "gpu_profile": _whole(saved.get("gpu_profile"), 1, 5) or GPU_GUARD_DEFAULTS["gpu_profile"]}


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
    model_family(model)
    # Before it had a setting of its own, the local model was OpenH3-IR's: kept so until it is chosen.
    local = saved.get("local_llm_model") or model
    try:
        model_family(local)
    except ValueError:
        local = DEFAULTS["local_llm_model"]
    return {"low_priority": bool(saved.get("low_priority")),
            "reserve_ram_gb": _gigabytes(saved.get("reserve_ram_gb")) or DEFAULT_RESERVE_GB,
            "h3_model": model,
            "local_llm_model": local,
            "default_workflow": {side: str(workflows.get(side) or "") for side in SIDES},
            # The image preset the viewer's Edit (pen) opens Generate with; empty: the Qwen-Image 2.1 edit workflow.
            "edit_preset": str(saved.get("edit_preset") or "")[:200],
            # The video preset the viewer's Edit menu opens Video with, its image in image 1 (an image-to-video one).
            "edit_video_preset": str(saved.get("edit_video_preset") or "")[:200],
            # Private mode: what is made is tagged NSFW, and Output opens on the NSFW filter. Kept over restarts.
            "private_mode": bool(saved.get("private_mode")),
            # Saved workflows the picker leaves out, as another stands for them (the Krea-2 ones the merged one does,
            # their looks kept as presets): still there for those presets and to open or continue what they made.
            "retired_workflows": _names(saved.get("retired_workflows")),
            # Titles: who titles a new film or set from its prompt (core/titles.py). Before it was a choice, Gemini titles
            # on meant "gemini".
            "title_source": saved["title_source"] if saved.get("title_source") in TITLE_SOURCES else "gemini" if saved.get("gemini_titles") else "off",
            # Pin the progress bar: scrolled away from the top, the header's progress bar stays, along the top of the screen.
            "pin_progress": bool(saved.get("pin_progress")),
            # The progress bar in the header at the top (on unless turned off), and the footer's Status button filling
            # as the run goes, with its percentage in the corner.
            "top_progress": bool(saved.get("top_progress", True)),
            "status_progress": bool(saved.get("status_progress")),
            # Each section in a box of its own (the theme's panel colour), or straight on the background.
            "theme_boxes": bool(saved.get("theme_boxes", True)),
            "page_swipe": bool(saved.get("page_swipe", True)),
            "page_animation": saved.get("page_animation") if saved.get("page_animation") in PAGE_ANIMATIONS else DEFAULTS["page_animation"],
            "page_speed": saved.get("page_speed") if saved.get("page_speed") in PAGE_SPEEDS else DEFAULTS["page_speed"],
            "output_order": saved.get("output_order", []),
            **_gpu_guard(saved),
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
            if changes["h3_model"] not in {model["id"] for model in local_models()}:
                raise ValueError("Unknown OpenH3-IR model.")
            current["h3_model"] = changes["h3_model"]
        if "local_llm_model" in changes:
            if changes["local_llm_model"] not in {model["id"] for model in local_models()}:
                raise ValueError("Unknown local LLM model.")
            current["local_llm_model"] = changes["local_llm_model"]
        if "private_mode" in changes:
            current["private_mode"] = bool(changes["private_mode"])
        if "retired_workflows" in changes:
            if not isinstance(changes["retired_workflows"], list):
                raise ValueError("Retired workflows are a list of workflow names.")
            current["retired_workflows"] = _names(changes["retired_workflows"])
        if "title_source" in changes:
            if changes["title_source"] not in TITLE_SOURCES:
                raise ValueError("Unknown title source.")
            current["title_source"] = changes["title_source"]
        for key in ("pin_progress", "top_progress", "status_progress", "theme_boxes", "page_swipe"):
            if key in changes:
                current[key] = bool(changes[key])
        for key, allowed, what in (("page_animation", PAGE_ANIMATIONS, "page animation"), ("page_speed", PAGE_SPEEDS, "page animation speed")):
            if key in changes:
                if changes[key] not in allowed:
                    raise ValueError(f"Unknown {what}.")
                current[key] = changes[key]
        if "output_order" in changes:
            ids = changes["output_order"]
            if (not isinstance(ids, list) or any(not isinstance(key, str) or not key.startswith(("image:", "film:"))
                                                or not key.split(":", 1)[1] for key in ids)
                    or len(ids) != len(set(ids))):
                raise ValueError("Output order must list each image batch or film once.")
            # Only shown items trade places; a hidden filter's items keep their slots.
            order = current["output_order"]
            known = set(order)
            order = [key for key in ids if key not in known] + order
            selected = set(ids)
            slots = iter(ids)
            current["output_order"] = [next(slots) if key in selected else key for key in order]
        if "theme" in changes:
            if not isinstance(changes["theme"], str) or changes["theme"] not in THEMES:
                raise ValueError("Unknown theme.")
            current["theme"] = changes["theme"]
        if "gpu_guard" in changes:
            current["gpu_guard"] = bool(changes["gpu_guard"])
        for key in ("gpu_restart_above", "gpu_rearm_at"):
            if key in changes:
                value = _whole(changes[key], GPU_LOWEST_C, GPU_HIGHEST_C)
                if value is None:
                    raise ValueError(f"Temperatures are whole degrees from {GPU_LOWEST_C} to {GPU_HIGHEST_C} C.")
                current[key] = value
        if current["gpu_rearm_at"] >= current["gpu_restart_above"]:
            raise ValueError("The cool-down temperature must be below the restart temperature.")
        if "gpu_profile" in changes:
            profile = _whole(changes["gpu_profile"], 1, 5)
            if profile is None:
                raise ValueError("The Afterburner profile is 1 to 5.")
            current["gpu_profile"] = profile
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
