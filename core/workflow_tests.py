"""
Workflow comparisons: one prompt, as written and on one seed, through every image workflow of a kind (text to image, or
edit) at that workflow's own default settings, as one set. With a LoRA comparison (core/lora_tests.py) asked for too,
each workflow runs it with its own style LoRAs; one that has none runs once.
"""
import json
import os

from core import lora_tests, workflow_options
from core.saved_workflows import picker_label

ENV = "GEN_CENTER_WORKFLOW_TEST"
# What the form's "workflow_test" asks for, and the set's workflow pill for it.
KINDS = {"t2i": "All T2I workflows", "edit": "All edit workflows"}
# What a LoRA comparison asks for, taken to each workflow: the LoRA and strength chosen on the form are the form
# workflow's own, so each other one starts from its own.
LORA_FIELDS = ("lora_strength_test", "lora_style_test", "lora_test_step")


def requested(form):
    """The kind asked for ("t2i" or "edit"; the form's switches workflow_test_t2i and workflow_test_edit), or None."""
    return next((kind for kind in KINDS if form.get(f"workflow_test_{kind}") not in (None, "", "0")), None)


def made_for(kind, takes, images=0):
    """
    Whether a workflow belongs in this comparison, as Automatic picks (panel/image.py): text to image takes no image;
    an edit needs one, and takes as many as were given.
    """
    if kind == "t2i":
        return takes["max_images"] == 0
    return 1 <= takes["min_images"] <= images <= takes["max_images"]


def variations(kind, entries, images=0, form=None, private=False):
    """
    Each usable image workflow of that kind, in name order, as the set's images: [{"kind", "workflow", "label"}], each
    with its "lora_test" when the form asks for a LoRA comparison and that workflow has a style LoRA to compare.
    """
    if kind == "edit" and not images:
        raise ValueError("An edit comparison needs the image to edit: choose one.")
    if kind == "t2i" and images:
        raise ValueError("A text-to-image comparison makes images from text alone: leave the image out.")
    asked = {field: (form or {}).get(field) for field in LORA_FIELDS}
    found = []
    for entry in entries:
        if entry.get("pipeline") != "image" or "problem" in entry or not made_for(kind, entry["takes"], images):
            continue
        # Named as Generate's picker names it, as each image's title and its pill in the viewer.
        workflow = {"kind": kind, "workflow": entry["path"], "label": picker_label(entry["path"], "image")}
        try:
            loras = lora_tests.variations(asked, entry["takes"].get("options") or [], private)
        except ValueError:
            loras = []  # No style LoRA it can compare (or not at that increment): it runs once, at its defaults
        found += [{**workflow, "lora_test": lora} for lora in loras] or [workflow]
    if not found:
        raise ValueError(f"No {'text-to-image' if kind == 't2i' else 'edit'} workflow can run to compare.")
    return found


def in_env(env=None):
    raw = (os.environ if env is None else env).get(ENV)
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("The saved workflow comparison is invalid.") from error
    lora_ok = lambda test: test is None or (isinstance(test, dict) and test.get("lora") == "1" and all(
        isinstance(test.get(key), str) for key in (workflow_options.LORA_NAME, workflow_options.LORA_STRENGTH)))
    if not isinstance(values, list) or not values or any(
            not isinstance(value, dict) or value.get("kind") not in KINDS or not lora_ok(value.get("lora_test"))
            or not all(isinstance(value.get(key), str) for key in ("workflow", "label")) for value in values):
        raise ValueError("The saved workflow comparison is invalid.")
    return values


def shots(template, values, seed):
    """The set's images: the same prompt and seed, each through its own workflow (and LoRA), named after them."""
    made = []
    for index, value in enumerate(values, 1):
        lora = value.get("lora_test")
        workflow = {key: value[key] for key in ("kind", "workflow", "label")}
        title = value["label"] + (f" · {workflow_options.lora_label(lora['lora_name'])} · {lora['lora_strength']}" if lora else "")
        made.append({**template, "number": index, "file": None, "seed": seed, "workflow_test": workflow, "title": title,
                     **({"lora_test": dict(lora)} if lora else {})})
    return made


def kind_of(shots):
    """The kind a set compares ("t2i", "edit"), or None for a set that isn't a workflow comparison."""
    return next((shot["workflow_test"]["kind"] for shot in shots or []
                 if isinstance(shot.get("workflow_test"), dict) and shot["workflow_test"].get("kind") in KINDS), None)


def pill(shots):
    """The set's workflow pill ("All T2I workflows"), or None."""
    kind = kind_of(shots)
    return KINDS[kind] if kind else None


def shot_workflow(shot):
    """The workflow one comparison image ran through, as its pill says it (as Generate's picker names it), or None."""
    test = shot.get("workflow_test")
    if not isinstance(test, dict):
        return None
    return picker_label(test["workflow"], test.get("label")) if test.get("workflow") else test.get("label")
