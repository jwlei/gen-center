"""
Comparisons of the files a workflow runs: its Model, Text encoder and VAE (core/workflow_options.py's pickers). The
same prompt, as written, and the same seed through each installed one, as one set, everything else as set. Several at
once make every combination of them; a LoRA comparison (core/lora_tests.py) with it runs in each. They travel with
the LoRA one's: each image's settings are what it changes over the set's (pipelines/image/main.py).
"""
import os

from core import workflow_options

# The form's switches, and the setting each compares.
KINDS = {"model_test": workflow_options.MODEL, "encoder_test": workflow_options.ENCODER, "vae_test": workflow_options.VAE}
LABELS = {workflow_options.MODEL: "Model", workflow_options.ENCODER: "Text encoder", workflow_options.VAE: "VAE"}
FILES = tuple(KINDS.values())


def most():
    """As many images as a set of your own prompt takes (pipelines/image/planner.py): a comparison is one."""
    from pipelines.image import planner
    return planner.MAX_IMAGES


def requested(form):
    return any(form.get(key) not in (None, "", "0") for key in KINDS)


def variations(form, options):
    """Each combination of the files asked to be compared, as settings: [{"model_file": ..., "vae_file": ...}]."""
    if not requested(form):
        return []
    found = {option["id"]: option for option in options}
    combinations = [{}]
    for key, option_id in KINDS.items():
        if form.get(key) in (None, "", "0"):
            continue
        option = found.get(option_id)
        choices = (option or {}).get("choices") or []
        if len(choices) < 2:
            raise ValueError(f"This workflow has no other {LABELS[option_id].lower()} installed to compare.")
        combinations = [{**combination, option_id: choice} for combination in combinations for choice in choices]
    if len(combinations) > most():
        raise ValueError(f"That makes {len(combinations)} images; compare fewer at once (up to {most()}).")
    return combinations


def combine(loras, files):
    """A LoRA comparison in each file comparison's images: every LoRA variation with every file one."""
    if not files:
        return loras
    if not loras:
        return files
    if len(loras) * len(files) > most():
        raise ValueError(f"That makes {len(loras) * len(files)} images; compare fewer at once (up to {most()}).")
    return [{**lora, **file} for file in files for lora in loras]


def short(name):
    """A file as it's said: its name, without its folder or .safetensors."""
    return os.path.splitext(os.path.basename(str(name).replace("\\", "/")))[0]


def label(test, tests=()):
    """
    What one image of a file comparison ran with, as its pill says it: each file by what tells it apart from the
    others compared with it (tests: every image's settings), "Model int8 mixed · Encoder abliterated · VAE Krea2Real".
    None for one that compared no files.
    """
    from core import model_files
    kinds = {setting: kind for kind, setting in model_files.SETTINGS.items()}
    parts = []
    for key in FILES:
        if isinstance(test, dict) and test.get(key):
            others = list(dict.fromkeys(other[key] for other in tests if isinstance(other, dict) and other.get(key)))
            parts.append(f"{model_files.LABELS[kinds[key]]} {model_files.distinct(test[key], others)}")
    return " · ".join(parts) or None


def tested(shots):
    """
    Each kind of file a set compared, with each one it ran, as its pills: [("model", "Model: Krea-2 Turbo fp8, int8"),
    ...] in model_files' kinds. [] for a set that didn't compare any.
    """
    from core import model_files
    kinds = {setting: kind for kind, setting in model_files.SETTINGS.items()}
    found = {}
    for shot in shots or []:
        test = shot.get("lora_test")
        for key in FILES:
            if isinstance(test, dict) and test.get(key):
                values = found.setdefault(key, [])
                if test[key] not in values:
                    values.append(test[key])
    return [(kinds[key], model_files.several(kinds[key], values)) for key, values in found.items() if len(values) > 1]
