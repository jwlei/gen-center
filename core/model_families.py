"""
Which model family a workflow runs, so a workflow saved in ComfyUI is grouped, labelled and given its family's default
preset without anyone telling the panel. One table (FAMILIES): adding a family is one line here.

How a workflow's family is found, most telling first:

    1. The diffusion model's file name (unet_name, ckpt_name...), by the words in FAMILIES' names: krea2_turbo_fp8 is
       Krea-2. What the user sees and picks, and what a fine-tune keeps.
    2. A node only that family has, as MiniMax H3's own nodes.
    3. The type its text encoder is loaded as (Load CLIP's type). ComfyUI keeps that list up to date itself, so a
       family it learns tomorrow is found too, under a label made from its type, until core/models/ names it.
    4. The words in the workflow's own name.

Sources: ComfyUI's CLIPLoader and DualCLIPLoader types (object_info, November 2026), docs.comfy.org/built-in-nodes/
ClipLoader, the ComfyUI changelog, and the pull requests adding FLUX.3 (#17064) and JoyImage (#14428).

The image side tells some models within a family apart (pipelines/image/models.py: Qwen-Image 2.1 from Qwen-Image-Edit
2511), as their limits differ: where it knows the model, that is the workflow's family (family_for()).
"""
import re

from core import models as known_models
from core.models import Family  # noqa: F401, as it was reached here


# The families, one file each where the panel knows more of them than their names (core/models/<family>.py), the rest
# a line each in core/models/others.py.
FAMILIES = known_models.FAMILIES

# Where the text encoder is loaded, and the input saying as what.
ENCODER_LOADERS = ("CLIPLoader", "DualCLIPLoader", "TripleCLIPLoader", "QuadrupleCLIPLoader", "CLIPLoaderGGUF", "DualCLIPLoaderGGUF")
# Inputs that name the diffusion model's file, on whatever node loads it.
MODEL_INPUTS = ("unet_name", "ckpt_name", "model_name")


def _words(value):
    return re.findall(r"[a-z0-9]+", str(value or "").lower())


def _phrase_in(words, phrase):
    """Whether each word of phrase is among words, side by side: "wan2 2" is in wan2_2_t2v, not in wan2_flux_2."""
    wanted = phrase.split()
    return any(words[at:at + len(wanted)] == wanted for at in range(len(words) - len(wanted) + 1))


def by_name(value):
    """The family a file or workflow name says, or None. The longest phrase wins: "flux 2" over "flux"."""
    words = _words(value)
    found = [(len(phrase.split()), len(phrase), family) for family, entry in FAMILIES.items()
             for phrase in entry.names if _phrase_in(words, phrase)]
    return max(found)[2] if found else None


def by_encoder(kind):
    """The family Load CLIP's type is, or that type itself for one this table doesn't name yet."""
    if not isinstance(kind, str) or not kind:
        return None
    return next((family for family, entry in FAMILIES.items() if kind in entry.encoders), kind)


def label(family):
    """What the panel calls a family: its label, or one made from an id this table doesn't name ("boogu": "Boogu")."""
    if not family:
        return ""
    entry = FAMILIES.get(family)
    return entry.label if entry else family.replace("_", " ").strip().title()


def _encoder_types(spec):
    """The types a Load CLIP node's spec offers, as object_info gives them (older ComfyUI: a list; newer: COMBO options)."""
    config = spec.get("input", {}).get("required", {}).get("type") or []
    if config and isinstance(config[0], list):
        return config[0]
    return config[1].get("options", []) if len(config) > 1 and isinstance(config[1], dict) else []


def available(url, timeout=10):
    """
    The model families ComfyUI can load now, by asking it which types Load CLIP takes: [{id, label, kind, known}], known
    false for one this table doesn't name yet (it still works, under a label made from its type). Raises
    requests.RequestException when ComfyUI can't be reached.
    """
    import requests
    found = []
    for loader in ENCODER_LOADERS[:2]:
        response = requests.get(f"{url}/object_info/{loader}", timeout=timeout)
        response.raise_for_status()
        found += _encoder_types(response.json().get(loader, {}))
    families = {}
    for kind in found:
        family = by_encoder(kind)
        if family and family not in families:
            entry = FAMILIES.get(family)
            families[family] = {"id": family, "label": label(family), "kind": entry.kind if entry else "", "known": bool(entry)}
    return sorted(families.values(), key=lambda family: (not family["known"], family["label"].casefold()))


def _model_names(api):
    """The file names of the diffusion models the workflow loads, the one the sampler uses first."""
    from core import workflow_options
    first = workflow_options._workflow_model(api)
    names = [first] if first else []
    # Not a LoRA's or an upscaler's: an H3 workflow may upscale with LTX's latent upscaler.
    names += [node["inputs"][key] for node in api.values() for key in MODEL_INPUTS
              if isinstance(node.get("inputs", {}).get(key), str) and not re.search(r"lora|upscale", node.get("class_type", ""), re.I)]
    return names


def family_of(api, workflow_name=""):
    """The family of the model an API-format workflow runs (see the top of this file), or None."""
    for name in _model_names(api):
        found = by_name(name)
        if found:
            return found
    for node in api.values():
        kind = node.get("class_type", "")
        found = next((family for family, entry in FAMILIES.items() if any(kind.startswith(start) for start in entry.nodes)), None)
        if found:
            return found
    for node in api.values():
        if node.get("class_type") in ENCODER_LOADERS:
            found = by_encoder(node.get("inputs", {}).get("type"))
            if found:
                return found
    return by_name(workflow_name)


def family_for(api, workflow_name="", image_model=None):
    """
    The family a workflow is listed and given defaults under. On the image side, the model pipelines/image/models.py
    knows it for (Qwen-Image 2.1's edit and make workflows are one model), else family_of().
    """
    if image_model:
        from pipelines.image import models
        return models.FAMILIES.get(image_model, image_model)
    return family_of(api, workflow_name)


def family_label(family):
    """label(), with the image side's own names for the models it tells apart."""
    from pipelines.image import models
    return models.LABELS.get(family) or label(family)


# Family names that are ordinary words too, as a style LoRA may be named: "chroma_glow" is no Chroma LoRA. A model's
# file is still found by them (by_name), where a LoRA's name would mislead.
STYLE_WORDS = {"chroma", "cosmos", "pony", "neta", "mochi", "lens", "illustrious", "ace"}


def lora_tokens():
    """The words in a LoRA's or model's name that say its family, by core/lora_check.py's names for them."""
    found = {}
    for family, entry in FAMILIES.items():
        words = {phrase for phrase in entry.names if " " not in phrase} - STYLE_WORDS
        if words:
            found.setdefault(entry.lora or family, set()).update(words)
    return found
