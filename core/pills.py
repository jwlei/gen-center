"""
Pills: what a film or an image set was made with, in short (workflow, upscale, how clips connect, OpenH3-IR, LoRA,
sampler and steps, CFG,
who wrote the prompts: an LLM or your exact prompt, and which LLM), and which of those tell it apart from its siblings: what else was made from the same prompt.

Live, Output marks the pills that differ from its siblings as they are now. Fixed, a new film's or set's file name
takes the differing ones when it is made (fixed_tag), in place of a bare _2, _3.
"""
import re

from core import workflow_options

# How a film's clips connect, in short: the long names are Generate's "How clips connect".
CONNECTIONS = {"chain": "Continuous take", "image": "Separate moments", "director": "H3 Motion Director",
               "multishot": "H3 Multishot", "infinite": "H3 Infinite continuation"}
# The order pills are shown in, after the differing ones.
KINDS = ("workflow", "prompt", "upscale", "clips", "openh3", "lora", "sampling", "cfg", "llm")
# The pills that are always first, whether or not they differ: the workflow, who writes the prompts, and which LLM.
LEADING = ("workflow", "prompt", "llm")


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


def run_facts(state, pipeline, workflow_name):
    """A saved run's facts as it was set up: what a new file name is told apart by (fixed_tag)."""
    if pipeline == "video":
        return facts(workflow_name, latent_description(state.options), state.connection_mode or state.start,
                     state.h3_mode, state.h3_creativity, workflow_options.loras_used(state.workflow, state.options, "video"),
                     state.llm, state.direct, workflow_options.sampling_used(state.workflow, state.options, "video"),
                     workflow_options.cfg_used(state.workflow, state.options, "video"))
    return facts(workflow_name, image_upscale_description(state.options),
                 loras=workflow_options.loras_used(state.workflow, state.options, "image"), llm=state.llm, direct=state.direct,
                 sampling=workflow_options.sampling_used(state.workflow, state.options, "image"),
                 cfg=workflow_options.cfg_used(state.workflow, state.options, "image"))


def run_stamp(run_id):
    """A run's time from its id (run_20261109_111347 -> 1113): what tells apart two made the same way."""
    match = re.search(r"_(\d{2})(\d{2})\d{2}$", run_id or "")
    return f"{match.group(1)}{match.group(2)}" if match else ""


def facts(workflow=None, upscaled=None, clips=None, h3_mode=None, h3_creativity=None, loras=(), llm=None, direct=False, sampling=None, cfg=None):
    """What it was made with, as (kind, text), in the order they are shown."""
    found = []
    if workflow:
        found.append(("workflow", workflow))
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
    # Who wrote the prompts: your own, word for word, or an LLM from your idea; which LLM is its own pill, later.
    found.append(("prompt", "Exact prompt" if direct else "LLM"))
    if llm and not direct:
        found.append(("llm", llm))
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


def pills(own, others, lead=LEADING):
    """
    Its pills: the workflow always first, then Exact prompt or LLM and, for an LLM, which one; then those that tell it
    apart from its siblings, marked, then the rest: [{"text", "kind", "diff"}]. What it lacks and a sibling has isn't
    a pill of its own: the sibling's is marked. lead: the kinds that come first, in order.
    """
    differing = _differing(own, others) if others else set()
    shown = [{"text": text, "kind": kind, "diff": kind in differing} for kind, text in own]
    order = {kind: number for number, kind in enumerate(KINDS)}
    first = {kind: number for number, kind in enumerate(lead)}
    return sorted(shown, key=lambda pill: (first.get(pill["kind"], len(lead)), not pill["diff"], order.get(pill["kind"], len(KINDS))))


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
    differing = [pill["text"] for pill in pills(own, others, ("workflow",)) if pill["diff"] and pill["kind"] != "workflow"]
    tag = "_".join(_slug(text) for text in differing[:2]) or stamp
    return tag[:48].strip("_-")
