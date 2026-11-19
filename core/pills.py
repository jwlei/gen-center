"""
Pills: what a film or an image set was made with, in short (workflow, its mode, who wrote the prompts and what helped,
LoRA, the files it ran, upscale, how clips connect, OpenH3-IR, sampler and steps, CFG), and which of those tell it apart
from its siblings: what else was made from the same prompt.

Live, Output marks the pills that differ from its siblings as they are now. Fixed, a new film's or set's file name
takes the differing ones when it is made (fixed_tag), in place of a bare _2, _3.
"""
import os
import re

from core import file_tests, llm_tests, lora_tests, model_files, test_names, workflow_options, workflow_tests

# How a film's clips connect, in short: the long names are Generate's "How clips connect".
CONNECTIONS = {"chain": "Continuous take", "image": "Separate moments", "director": "H3 Motion Director",
               "multishot": "H3 Multishot", "infinite": "H3 Infinite continuation"}
# The order pills are always shown in, differing or not, so each is where you look for it: what tells two apart most
# often first. The workflow, its mode (T2I, I2I...), a comparison's name ("VAE test"), who wrote the prompts (which LLM,
# or your exact prompt) and what helped (Prompt enhancer, I2P), the LoRAs; then the files it ran and the rest.
KINDS = ("workflow", "mode", "test", "llm", "writer", "openh3", "lora", "model", "encoder", "vae", "upscale", "clips",
         "sampling", "cfg")
# What helped write the prompts, as its pill says it.
WRITERS = {"Image to prompt": "I2P"}
# An image workflow's mode switch (FoxFurEssence's text2image | image2image | inpaint), as its pill says it: as the
# Mode picker does (panel/static/image-inputs.js MODE_LABELS), painted areas Inpaint too and references R2I.
IMAGE_MODES = {"text2image": "T2I", "image2image": "I2I", "inpaint": "Inpaint"}
REGION_MODES = {"areas": "Inpaint", "expand": "Expand"}


def image_mode(state):
    """
    How an image set was made, as the Mode picker says it: from text (T2I), from an image (I2I, Inpaint, or Edit for a
    model that edits by instruction), a new picture from references (R2I), or Inpaint of painted parts, or Expand.
    From what the set keeps, so every set has it, however old.
    """
    kind = (getattr(state, "region", None) or {}).get("kind")
    if kind:
        return REGION_MODES.get(kind, str(kind).title())
    if getattr(state, "compose", False):
        return "R2I"
    options = getattr(state, "options", None) or {}
    for key, value in options.items():
        if key.startswith("one_of_") and "." not in key and str(value).lower() in IMAGE_MODES:
            return IMAGE_MODES[str(value).lower()]
    # The picture image to prompt describes isn't one it edits.
    edited = (getattr(state, "image_count", 0) or 0) - (1 if options.get("image_to_prompt") == workflow_options.ON else 0)
    return "Edit" if edited > 0 else "T2I"


def video_mode(state):
    """How a film was made: from text (T2V), from an image (I2V), or from several or reference videos (R2V)."""
    images = getattr(state, "image_count", 1) or 0
    if getattr(state, "ref_videos", None) or images > 1:
        return "R2V"
    return "I2V" if images else "T2V"


def video_writer(state):
    """What helped write a film's prompts: the workflow's own prompt enhancer, where it wrote any clip's; else None."""
    return "Prompt enhancer" if any(shot.get("workflow_enhanced_prompt") for shot in getattr(state, "shots", None) or []) else None


def image_writer(state):
    """What helped write an image set's prompts: the workflow's own enhancer or image to prompt, or I2P; else None."""
    writer = workflow_options.prompt_writer_used(state.workflow, state.options, state.form)
    return writer[1] if writer else "I2P" if getattr(state, "looked", False) else None


def latent_description(options):
    """The latent upscale a film was made with, or None."""
    options = options or {}
    preset = options.get("latent_upscale")
    if not preset or preset == "Off":
        return None
    detail = f", denoise {options.get('latent_upscale_denoise', '0.5')}" if preset == "Custom" else ""
    return f"Latent, {preset}{detail}, {options.get('latent_upscale_mp', '1')} MP"


def image_upscale_description(options):
    """The upscale an image set was made with (Upscale under Resolution), or None."""
    options = options or {}
    method = options.get("image_upscale")
    if not method or method == workflow_options.NO_IMAGE_UPSCALE:
        return None
    denoise = options.get("image_upscale_denoise")
    return f"{method}, denoise {denoise}" if denoise and method != "UltraSharp" else method


def image_loras(state):
    """
    The LoRAs an image set's pills name: the ones its workflow ran with. A LoRA comparison names none: its test pill
    says it's one ("LoRA strength test"), and each image's own pill its LoRA and strength.
    """
    if lora_tests.tested(state.shots):
        return []
    return workflow_options.loras_used(state.workflow, state.options, "image")


def image_files(state):
    """
    The files an image set ran, as pills (core/model_files.py): what a file comparison compared, each kind with the
    ones it ran; else the set's own, from its settings or what ComfyUI wrote into its first image. A workflow
    comparison runs each workflow's own, so it has none.
    """
    if workflow_tests.kind_of(state.shots):
        return []
    # What a comparison varied isn't a pill of the set's (its test pill says it is one); what all its images shared is.
    varied = {kind for kind, _ in file_tests.tested(state.shots)}
    return [(kind, text) for kind, text in model_files.pills(model_files.used(state.options, first_image(state))) if kind not in varied]


def first_image(state):
    """Where the first image a set made is, or None."""
    shot = next((shot for shot in state.shots or [] if shot.get("file")), None)
    try:
        return os.path.join(state.output_dir, shot["file"]) if shot else None
    except (AttributeError, TypeError):
        return None


def run_facts(state, pipeline, workflow_name):
    """A saved run's facts as it was set up: what a new file name is told apart by (fixed_tag)."""
    if pipeline == "video":
        return facts(workflow_name, latent_description(state.options), state.connection_mode or state.start,
                     state.h3_mode, state.h3_creativity, workflow_options.loras_used(state.workflow, state.options, "video"),
                     state.llm, state.direct, workflow_options.sampling_used(state.workflow, state.options, "video"),
                     workflow_options.cfg_used(state.workflow, state.options, "video"), mode=video_mode(state),
                     prompt_writer=video_writer(state))
    # A workflow comparison's workflow pill says what it compares ("All T2I workflows"); an LLM comparison's LLM pill, "All LLMs".
    return facts(workflow_tests.pill(state.shots) or workflow_name, image_upscale_description(state.options),
                 files=image_files(state), test=test_names.of_shots(state.shots),
                 loras=image_loras(state), llm=llm_tests.pill(state.shots) or state.llm, direct=state.direct,
                 sampling=workflow_options.sampling_used(state.workflow, state.options, "image"),
                 cfg=workflow_options.cfg_used(state.workflow, state.options, "image"),
                 prompt_writer=image_writer(state), mode=image_mode(state))


def run_stamp(run_id):
    """A run's time from its id (run_20261109_111347 -> 1113): what tells apart two made the same way."""
    match = re.search(r"_(\d{2})(\d{2})\d{2}$", run_id or "")
    return f"{match.group(1)}{match.group(2)}" if match else ""


def facts(workflow=None, upscaled=None, clips=None, h3_mode=None, h3_creativity=None, loras=(), llm=None, direct=False, sampling=None, cfg=None,
          prompt_writer=None, files=(), test=None, mode=None):
    """
    What it was made with, as (kind, text). llm: which LLM wrote the prompts (none: your exact prompt). prompt_writer:
    what helped, its pill following the LLM's: the workflow's Prompt enhancer, or I2P.
    """
    found = []
    if workflow:
        found.append(("workflow", workflow))
    if mode:
        found.append(("mode", mode))
    if test:
        found.append(("test", test))
    # Who wrote the prompts: which LLM, or your own word for word (as the workflow's enhancer starts from); then what helped.
    found.append(("llm", "Exact prompt" if direct or not llm else llm))
    if prompt_writer:
        found.append(("writer", WRITERS.get(prompt_writer, prompt_writer)))
    found += list(files or ())
    if upscaled:
        found.append(("upscale", f"Upscaled: {upscaled}"))
    if clips:
        found.append(("clips", CONNECTIONS.get(clips, clips)))
    if h3_mode and h3_mode != "off":
        # How bold, not when: before review or each clip doesn't tell films apart as it reads.
        found.append(("openh3", f"OpenH3-IR: {h3_creativity[:1].upper()}{h3_creativity[1:]}" if h3_creativity else "OpenH3-IR"))
    found += [("lora", f"LoRA: {lora}") for lora in loras or ()]
    # The sampler and its steps, as it ran: "euler, 6 steps".
    if sampling:
        found.append(("sampling", sampling))
    if cfg:
        found.append(("cfg", f"CFG: {cfg}"))
    return found


def sibling_key(pipeline, prompt):
    """Made from the same prompt on the same side: spacing and case don't make it another."""
    words = " ".join(str(prompt or "").split()).casefold()
    return (pipeline, words) if words else None


def _differing(own, others):
    """The kinds whose pills aren't the same for this one and every sibling."""
    def of(found, kind):
        return frozenset(text for k, text in found if k == kind)
    return {kind for kind in KINDS if any(of(other, kind) != of(own, kind) for other in others)}


def pills(own, others):
    """
    Its pills, always in the order of KINDS, those that tell it apart from its siblings marked: [{"text", "kind",
    "diff"}]. What it lacks and a sibling has isn't a pill of its own: the sibling's is marked.
    """
    differing = _differing(own, others) if others else set()
    shown = [{"text": text, "kind": kind, "diff": kind in differing} for kind, text in own]
    order = {kind: number for number, kind in enumerate(KINDS)}
    return sorted(shown, key=lambda pill: order.get(pill["kind"], len(KINDS)))


def with_pills(items):
    """
    Gives each item its "pills", against the others with the same "_sibling" key, and drops that key: the prompt
    it is made from stays on the server. Each item carries its own "_facts".
    """
    groups = {}
    for item in items:
        if item.get("_sibling"):
            groups.setdefault(item["_sibling"], []).append(item)
    for item in items:
        siblings = [other["_facts"] for other in groups.get(item.get("_sibling"), []) if other is not item]
        item["pills"] = pills(item["_facts"], siblings)
    for item in items:
        item.pop("_sibling", None)
        item.pop("_facts", None)
        # A comparison says so in the theme's colour: its test pill ("VAE test"), second after its workflow.
        marked = item.pop("_comparison", None)
        marked = ("test",) if marked else ()
        for pill in item["pills"]:
            if pill["kind"] in marked:
                pill["comparison"] = True
    return items


def _slug(text):
    return re.sub(r"[^\w.]+", "-", text).strip("-")


def fixed_tag(own, others, stamp):
    """
    What a new film's or set's file name adds: up to two pills that differ from what the same prompt made before
    (the workflow is already in the name), or, with nothing different, its time; nothing when it is the first.
    """
    if not others:
        return ""
    differing = [pill["text"] for pill in pills(own, others) if pill["diff"] and pill["kind"] != "workflow"]
    tag = "_".join(_slug(text) for text in differing[:2]) or stamp
    return tag[:48].strip("_-")
