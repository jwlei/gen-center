"""
The files an image was made with (its Model, Text encoder and VAE), for its pills: which they were, and short, plain
names for them that fit a pill on a phone ("Krea-2 Turbo int8 mixed", "Qwen3-VL 4B abliterated", "Krea2Real").

Which they were: a comparison image's own (core/file_tests.py), else the run's settings (every run keeps them all
since Nov 2026), else what ComfyUI wrote into the image (the workflow it ran, in a PNG's "prompt"), so sets made
before then have them too. Never the workflow as it is now: it may have changed since.
"""
import json
import os
import re

from core import workflow_options

KINDS = ("model", "encoder", "vae")
# Each kind's setting (core/workflow_options.py) and the loader inputs that say it in a workflow ComfyUI ran.
SETTINGS = {"model": workflow_options.MODEL, "encoder": workflow_options.ENCODER, "vae": workflow_options.VAE}
LOADERS = {"model": {"UNETLoader": "unet_name", "UNETLoaderGGUF": "unet_name", "UnetLoaderGGUF": "unet_name", "CheckpointLoaderSimple": "ckpt_name", "CheckpointLoader": "ckpt_name"},
           "encoder": {"CLIPLoader": "clip_name", "DualCLIPLoader": "clip_name1", "H3ClipLoaderAny": "clip_name", "DualCLIPLoaderGGUF": "clip_name1"},
           "vae": {"VAELoader": "vae_name", "VAELoaderKJ": "vae_name"}}
LABELS = {"model": "Model", "encoder": "Encoder", "vae": "VAE"}
# Those whose names say little or too much: by their file's name, lower case, without its folder or extension.
KNOWN = {
    "krea2_turbo_fp8_scaled": "Krea-2 Turbo fp8", "krea2_turbo_fp8": "Krea-2 Turbo fp8", "krea2_turbo_bf16": "Krea-2 Turbo bf16",
    "krea2_turbo_int8_convrot": "Krea-2 Turbo int8", "krea2_turbo_convrot_int8mixed": "Krea-2 Turbo int8 mixed",
    "krea2_turbo_int8mixed": "Krea-2 Turbo int8 mixed", "krea2_turbo_nvfp4": "Krea-2 Turbo nvfp4", "krea2_turbo_mxfp8": "Krea-2 Turbo mxfp8",
    "qwen3vl4babliteratedcomfyui_v10_full_fp8": "Qwen3-VL 4B abliterated", "qwen3vl_4b_fp8_scaled": "Qwen3-VL 4B fp8",
    "qwen3vl_4b_bf16": "Qwen3-VL 4B bf16", "qwen3vl_4b_int8_convrot": "Qwen3-VL 4B int8", "qwen3vl_8b_int8_convrot": "Qwen3-VL 8B int8",
    "qwen3vl_32b_minimax_h3_int8_convrot": "Qwen3-VL 32B int8", "qwen3vl_32b_minimax_h3_int4_convrot": "Qwen3-VL 32B int4",
    "qwen3vl_32b_minimax_h3_nvfp4_awq": "Qwen3-VL 32B nvfp4", "qwen_2.5_vl_7b_fp8_scaled": "Qwen2.5-VL 7B fp8",
    "krea2realvae_v10": "Krea2Real", "qwen_image_vae": "Qwen-Image", "wan_2.1_vae": "WAN 2.1", "flux2-vae": "FLUX.2",
    "texture_fix_vae_for_qwen_image_2.1_bf16": "Qwen-Image 2.1 texture fix", "minimax_h3_image_vae_fp16": "MiniMax H3",
    "minimax_h3_image_pruned_int8_convrot": "MiniMax H3 Image int8", "qwen-image-2.1-turbo-q4_k_m": "Qwen-Image 2.1 Turbo Q4",
    "qwen_image_edit_2511_int8_convrot": "Qwen-Image-Edit 2511 int8",
    "moss_image_base_int8_convrot": "MOSS Image int8", "moss_pornmaster_sft_v1_int8_convrot_nsfw": "MOSS PornMaster SFT int8",
    "fibo2_edit_turbo_int8_convrot": "Fibo 2.0 Edit Turbo int8", "qwen3.5_9b_bf16": "Qwen3.5 9B bf16",
    "qwen3.5_9b_w4a8_gptq": "Qwen3.5 9B w4a8", "gemma_3_12b_it_fpmixed": "Gemma 3 12B", "gemma-3-12b-it-q2_k": "Gemma 3 12B Q2",
    "qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot": "Qwen3.5 9B (Qwen-Image T2I) int8",
    "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot": "Qwen3.5 9B (Qwen-Image I2I) int8",
}
# Short enough for a pill on a phone, its kind's word before it.
MOST = 26


def friendly(name):
    """A file as its pill says it: a known one by name, any other by its file's name, tidied and cut short."""
    stem = os.path.splitext(os.path.basename(str(name or "").replace("\\", "/")))[0]
    if stem.lower() in KNOWN:
        return KNOWN[stem.lower()]
    words = re.sub(r"[_\s]+", " ", stem).replace("fp8 scaled", "fp8").strip()
    return words if len(words) <= MOST else words[:MOST - 1].rstrip() + "…"


def files_in(api):
    """What a workflow ComfyUI ran loads, by kind: {"model": file, ...}, its first loader of each."""
    found = {}
    for node in (api or {}).values() if isinstance(api, dict) else ():
        if not isinstance(node, dict):
            continue
        for kind, loaders in LOADERS.items():
            name = (node.get("inputs") or {}).get(loaders.get(node.get("class_type"), ""))
            if kind not in found and isinstance(name, str) and name:
                found[kind] = name
    return found


_read = {}


def files_of_image(path):
    """What ComfyUI wrote into an image it made: the files the workflow it ran loads. {} where it wrote nothing."""
    try:
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size)
        if key not in _read:
            from PIL import Image
            with Image.open(path) as image:
                prompt = image.info.get("prompt")
            _read[key] = files_in(json.loads(prompt)) if isinstance(prompt, str) else {}
        return _read[key]
    except (OSError, ValueError, TypeError):
        return {}


def used(options, image=None):
    """The files a run or image was made with, by kind: its settings where it kept them, else what its image says."""
    options = options or {}
    found = {kind: options[setting] for kind, setting in SETTINGS.items() if options.get(setting)}
    if image and len(found) < len(KINDS):
        found = {**files_of_image(image), **found}
    return found


def pills(found):
    """The pills for them, in order: [("model", "Model: Krea-2 Turbo int8"), ...]."""
    return [(kind, f"{LABELS[kind]}: {friendly(found[kind])}") for kind in KINDS if found.get(kind)]


def distinct(name, names):
    """What tells one file apart from the others it's compared with: its short name less the words they all start with."""
    said = list(dict.fromkeys(friendly(other) for other in names))
    # Not compared with any other (the one file every image ran): said whole.
    if len(said) < 2:
        return friendly(name)
    words = [one.split(" ") for one in said]
    shared = 0
    while all(len(one) > shared + 1 for one in words) and len({tuple(one[:shared + 1]) for one in words}) == 1:
        shared += 1
    return " ".join(friendly(name).split(" ")[shared:])


def several(kind, names):
    """
    A pill for several of one kind (a comparison of them): what they share said once, then what tells each apart,
    "Models: int8 mixed, fp8, int8" for three Krea-2 Turbos.
    """
    return f"{LABELS[kind]}s: {', '.join(distinct(name, names) for name in names)}"


def encoder_base(name):
    """
    What text encoder a file is, less how it's stored: its model and size by name, any precision, quantization or
    tune after them ("qwen3vl4b" for qwen3vl_4b_fp8_scaled and qwen3VL4BAbliterated...). None where its name has no
    size (a "4b", "7b", "32b") to tell it by. A prompt enhancer tuned from one (Qwen3.5 9B's "_pe_" ones) is another.
    """
    stem = os.path.splitext(os.path.basename(str(name or "").replace("\\", "/")))[0].lower()
    if re.search(r"(^|[_.-])pe([_.-]|$)", stem):
        return None
    flat = re.sub(r"[^a-z0-9.]", "", stem)
    found = re.match(r"^(.*?\d+(?:\.\d+)?b)", flat)
    return found.group(1) if found else None


_shapes = {}


def vae_folders():
    """Where ComfyUI keeps VAEs."""
    from core import lora_check
    return [os.path.join(base, "models", "vae") for base in lora_check.comfyui_folders()]


def vae_shape(name):
    """
    A VAE's layers and their sizes, from its file's header (no weights read): two with the same can stand in for each
    other, whatever they're called. Its precision and quantization scales left out. None where it can't be read.
    """
    import struct
    for folder in vae_folders():
        path = os.path.join(folder, str(name).replace("/", os.sep))
        try:
            stat = os.stat(path)
        except OSError:
            continue
        key = (path, stat.st_mtime_ns, stat.st_size)
        if key not in _shapes:
            try:
                with open(path, "rb") as f:
                    size = struct.unpack("<Q", f.read(8))[0]
                    header = json.loads(f.read(size))
                header.pop("__metadata__", None)
                _shapes[key] = frozenset((layer, tuple(spec.get("shape") or ())) for layer, spec in header.items()
                                         if not re.search(r"scale|comfy_quant", layer))
            except (OSError, ValueError, struct.error):
                _shapes[key] = None
        return _shapes[key]
    return None
