"""LoRA family keywords and the Qwen-Image 2.1 tensor-architecture guard."""
import json
import os
import re
import struct

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
_found = {}
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


def lora_path(name):
    """The LoRA file ComfyUI lists by this name, or None."""
    for folder in comfyui_folders():
        path = os.path.join(folder, "models", "loras", name.replace("\\", os.sep).replace("/", os.sep))
        if os.path.isfile(path):
            return path
    return None


def _tokens(value):
    return re.findall(r"[a-z0-9]+", str(value).lower())


def _families(value):
    tokens = set(_tokens(value))
    return {family for family, aliases in FAMILY_TOKENS.items() if tokens & aliases}


def model_families(model):
    """Family keywords in an actual diffusion model filename or loader class name."""
    return _families(model) if model else set()


def lora_families(name):
    """The model-family keywords in a LoRA's filename or folder, possibly more than one."""
    return _families(name)


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


def _qwen_version(path):
    header = _header(path)
    if not isinstance(header, dict):
        return None
    names = [name for name in header if name != "__metadata__"]
    versions = set()
    for name in names:
        if _QWEN_21.search(name):
            versions.add(QWEN_21)
        if _QWEN_EARLIER.search(name):
            versions.add(QWEN_EARLIER)
    return versions.pop() if len(versions) == 1 else None


def family(name):
    """The exact Qwen generation from tensor names, if identifiable."""
    path = lora_path(name)
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _found:
        _found[key] = _qwen_version(path)
    return _found[key]


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
