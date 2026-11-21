"""
Which model a LoRA is for, from the file itself: its metadata, else the layout of its tensors, else (only when the file
says nothing) a family word in its name or folder. So a LoRA is found however it's named, and dropping one into
ComfyUI's loras folder is all it takes. Also the Qwen-Image 2.1 tensor-architecture guard.
"""
import json
import os
import re
import struct

from core import model_families
from core import models as known_models

QWEN_21, QWEN_EARLIER = "qwen_image_21", "qwen_image_earlier"
MOST_HEADER = 64 * 1024 * 1024
FAMILY_TOKENS = {
    "krea": {"krea", "krea2"},
    "moss": {"moss"},
    "qwen": {"qwen"},
    "minimax_h3": {"minimax", "h3"},
    "ltx": {"ltx", "ltxv"},
    "fibo": {"fibo", "fibo2"},
}
# Every other family core/model_families.py knows, by the words in its name, so a LoRA for one isn't hidden as unknown.
for _family, _words in model_families.lora_tokens().items():
    FAMILY_TOKENS.setdefault(_family, set()).update(_words)
_found = {}
# Each family's own tensor names, as trainers save them ("diffusion_model.blocks.0..." or kohya's "lora_unet_blocks_0_..."):
# its lora_signature in core/models/. SDXL's and FLUX.1's are there too, though the workflows here don't run them, so a
# LoRA for them is told apart rather than taken by its filename.
SIGNATURES = {family: re.compile(pattern, re.I) for family, pattern in known_models.lora_signatures().items()}
# Metadata trainers write that names the base model (kohya, modelspec, ComfyUI's own).
FAMILY_METADATA = ("ss_base_model_version", "modelspec.architecture", "base_model", "ss_sd_model_name")
# What only a LoRA (or LoKr, LoHa, DoRA) holds: a file with none of these is a whole model.
LORA_TENSOR = re.compile(r"lora_(?:a|b|down|up)(?:[._]|$)|[._]alpha$|lokr_|hada_|[._]diff(?:_b)?$|dora_scale", re.I)
WHOLE_MODEL = ("It's a whole model, not a LoRA: it goes in ComfyUI's diffusion_models or checkpoints folder, "
               "and as a LoRA it can't run.")
_QWEN_21 = re.compile(r"(?:^|[._])img_mlp\.(?:gate_up|gate_layer)(?:[._]|$)", re.I)
_QWEN_EARLIER = re.compile(r"(?:^|[._])img_mlp\.net\.(?:0\.proj|2)(?:[._]|$)", re.I)


def comfyui_folders():
    """Where ComfyUI may be: COMFYUI_DIR, and the folders around its launcher."""
    folders = []
    if os.getenv("COMFYUI_DIR"):
        folders.append(os.getenv("COMFYUI_DIR"))
    launcher = os.getenv("COMFYUI_LAUNCHER") or ""
    if launcher:
        here = os.path.dirname(os.path.abspath(launcher))
        folders += [os.path.join(here, "ComfyUI"), here]
    return [folder for folder in folders if os.path.isdir(os.path.join(folder, "models"))]


LORA_FOLDERS = ("loras",)
# Where ComfyUI's model loaders look: UNETLoader in diffusion_models (unet, as it was called), CheckpointLoader in checkpoints.
MODEL_FOLDERS = ("diffusion_models", "unet", "checkpoints")


def lora_path(name, kinds=LORA_FOLDERS):
    """The file ComfyUI lists by this name in one of these models folders (its LoRAs, unless told), or None."""
    for folder in comfyui_folders():
        for kind in kinds:
            path = os.path.join(folder, "models", kind, name.replace("\\", os.sep).replace("/", os.sep))
            if os.path.isfile(path):
                return path
    return None


def _tokens(value):
    return re.findall(r"[a-z0-9]+", str(value).lower())


def _families(value):
    tokens = set(_tokens(value))
    return {family for family, aliases in FAMILY_TOKENS.items() if tokens & aliases}


def model_families(model):
    """
    The families of a diffusion model or checkpoint: what its file says (metadata, else its tensors), else the family
    words in its filename or loader class name. So a model is known however it's named.
    """
    if not model:
        return set()
    found = inspected(model, MODEL_FOLDERS)
    if found and found["families"]:
        return set(found["families"])
    return _families(model)


def lora_families(name):
    """
    The model families a LoRA is for: what the file says (metadata, else its tensors), else the family words in its
    filename or folder. Possibly more than one; empty when nothing tells.
    """
    found = inspected(name)
    if found and found["families"]:
        return set(found["families"])
    return _families(name)


def not_a_lora(name):
    """Whether the file in the loras folder is really a whole model (a checkpoint or diffusion model)."""
    found = inspected(name)
    return bool(found and not found["lora"])


def private_lora(name):
    return bool(re.search(r"nsfw|uncensor", str(name), re.I))


def _header(path):
    """A safetensors header, or None when the file is absent, invalid, or too large to inspect."""
    try:
        with open(path, "rb") as f:
            size = struct.unpack("<Q", f.read(8))[0]
            if not 0 < size <= MOST_HEADER:
                return None
            return json.loads(f.read(size))
    except (OSError, ValueError, struct.error):
        return None


def _inspect(path):
    """What a LoRA file says about itself: {"families", "lora", "qwen"}, or None when its header can't be read."""
    header = _header(path)
    if not isinstance(header, dict):
        return None
    names = [name for name in header if name != "__metadata__"]
    meta = header.get("__metadata__") if isinstance(header.get("__metadata__"), dict) else {}
    families = {family for family, pattern in SIGNATURES.items() if any(pattern.search(name) for name in names)}
    if not families:
        families = set().union(*(_families(meta.get(key)) for key in FAMILY_METADATA if meta.get(key)))
    return {"families": families, "lora": any(LORA_TENSOR.search(name) for name in names), "qwen": _qwen_version(names)}


def _qwen_version(names):
    versions = set()
    for name in names:
        if _QWEN_21.search(name):
            versions.add(QWEN_21)
        if _QWEN_EARLIER.search(name):
            versions.add(QWEN_EARLIER)
    return versions.pop() if len(versions) == 1 else None


def inspected(name, kinds=LORA_FOLDERS):
    """_inspect for the file ComfyUI lists by this name, read once per version of the file; None when it isn't here."""
    path = lora_path(name, kinds) if isinstance(name, str) and name else None
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _found:
        _found[key] = _inspect(path)
    return _found[key]


def family(name):
    """The exact Qwen generation from tensor names, if identifiable."""
    found = inspected(name)
    return found["qwen"] if found else None


def display_label(name):
    """A compact picker label; strip leading family tags, without changing the file identifier."""
    stem = os.path.splitext(os.path.basename(str(name).replace("\\", "/")))[0]
    stem = re.sub(r"(?:_1|\s*\(1\))$", "", stem)
    tokens = _tokens(stem)
    aliases = set().union(*FAMILY_TOKENS.values())
    stripped = False
    while tokens and tokens[0] in aliases:
        tokens.pop(0)
        stripped = True
    return "_".join(tokens) if stripped and tokens else stem


def problem(name, model):
    """Why this LoRA does nothing on, or cannot be verified for, this model; None when compatible."""
    if not_a_lora(name):
        return WHOLE_MODEL
    found = lora_families(name)
    if family(name) in (QWEN_21, QWEN_EARLIER):
        found.add("qwen")
    target = model_families(model)
    if not found:
        return None
    if not target:
        return f"Its model family can't be identified, so {name} can't be checked safely."
    if not found & target:
        return f"It was made for {', '.join(sorted(found))}, not {', '.join(sorted(target))}."
    if "qwen" in found and "qwen" in target and family(name) == QWEN_EARLIER and re.search(
            r"(?:^|[^a-z0-9])qwen(?:[-_ ]?image)?[-_ ]?2[._-]?1(?:$|[^a-z0-9])", str(model), re.I):
        return "It was made for an earlier Qwen-Image (1.x, 2512 or Edit): on Qwen-Image 2.1 it does nothing."
    return None
