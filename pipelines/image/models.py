"""
What sets each image model apart: how big it can make an image well, how many prompts an LLM can write for it in one
reply, what it calls its images. Each model's own figures, and where they come from, are in its family's file in
core/models/ (krea2.py, qwen_image.py...); these are the tables made from them that the image side reads.
core/saved_workflows.py says which model a workflow runs.
"""
from core.models import IMAGE_MODELS
from pipelines.image.media import PIXELS_PER_MEGAPIXEL

FIBO2, KREA2, MOSS_IMAGE, QWEN_IMAGE_EDIT = "fibo2", "krea2", "moss_image", "qwen_image_edit"
QWEN_IMAGE_21, QWEN_IMAGE_21_EDIT = "qwen_image_21", "qwen_image_21_edit"
MINIMAX_H3_IMAGE, MINIMAX_H3_IMAGE_EDIT = "minimax_h3_image", "minimax_h3_image_edit"


def _each(field):
    """{model: its value of field}, for the models that have one."""
    return {model: getattr(entry, field) for model, entry in IMAGE_MODELS.items() if getattr(entry, field)}


LABELS = _each("label")
# One model, as the Model picker lists it: its edit workflows are the same model as its text ones.
FAMILIES = _each("same_as")
# The most megapixels each makes (before any upscale; a preset size above it is made at its shape within it). A model
# left out takes what the form offers.
MOST_MEGAPIXELS = _each("most_megapixels")
# Where the form starts for each, when it has no size of its own to start from; below which it starts there instead.
DEFAULT_MEGAPIXELS = _each("default_megapixels")
LEAST_MEGAPIXELS = _each("least_megapixels")
# How many prompts one reply can hold, where they are long.
MOST_WRITTEN = _each("most_written")
# How many images it takes at most, where that's fewer than its workflow has room for.
MOST_IMAGES = _each("most_images")
# The model's tokens a job has room for on this card, image made and images shown together, in megapixels. References
# are shrunk to share what's left: see reference_sizes().
TOKEN_BUDGET = _each("token_budget")
# What it calls the images it's given, in a prompt.
IMAGE_NAMES = _each("image_name")
# Models that can make a new picture from images used as references, rather than edit image 1, by the workflow option
# that gives it a size of its own; and the most megapixels they make so.
COMPOSE_SWITCH = _each("compose_switch")
MOST_MEGAPIXELS_COMPOSE = _each("most_megapixels_compose")
# Models that can work on part of an image: one marked in a colour on a second image it's shown (see regions.py).
REGION_EDITS = tuple(_each("regions"))
# Models that make an image with a transparent background when the prompt says so, and how to say it.
TRANSPARENT = _each("transparent")
# Standard reference detail: images shown to the model besides the one it edits, at about a megapixel each.
REFERENCE_MEGAPIXELS = 1.0


def label(model):
    return LABELS.get(model, "This workflow's model")


def size_problem(model, width, height):
    """Why this model shouldn't make an image this size, or None."""
    most = MOST_MEGAPIXELS.get(model)
    if not most or width * height <= most * PIXELS_PER_MEGAPIXEL:
        return None
    return (f"{label(model)} makes images up to {most:g} megapixels, and {width}x{height} is {width * height / PIXELS_PER_MEGAPIXEL:.1f}. "
            "Choose fewer megapixels or a smaller size.")


def count_problem(model, count, direct):
    """Why the LLM can't write this many prompts for this model in one go, or None."""
    most = MOST_WRITTEN.get(model)
    if direct or not most or count <= most:
        return None
    return f"The LLM writes at most {most} prompts for {label(model)} at a time: its prompts are long. Make fewer, or use your own prompt."


def most_megapixels(model, compose=False):
    return (MOST_MEGAPIXELS_COMPOSE.get(model) if compose else None) or MOST_MEGAPIXELS.get(model)


def size_problem_for(model, width, height, compose=False):
    most = most_megapixels(model, compose)
    if not most or width * height <= most * PIXELS_PER_MEGAPIXEL:
        return None
    return (f"{label(model)} makes images up to {most:g} megapixels{' from references' if compose else ''}, and {width}x{height} is "
            f"{width * height / PIXELS_PER_MEGAPIXEL:.1f}. Choose fewer megapixels or a smaller size.")


def image_name(model, number):
    """What the prompt calls image number, for this model."""
    return IMAGE_NAMES.get(model, "image {}").format(number)


def reference_sizes(model, made, shown, detail="standard", editing=True):
    """
    The size to show the model each of its images at, so all of them fit in what the card holds with the one it makes.
    made: (width, height) of the image it makes. shown: [(width, height)] of the images it's shown, image 1 first.
    editing: image 1 is the image being edited, made at the size of the one made, and left as it is. The rest are at
    most a megapixel each with standard detail (Kokon's reference detail), less if they'd crowd out the rest. Full
    keeps them as they are. Returns [(width, height)], each on the 32 grid, its shape kept.
    """
    budget = TOKEN_BUDGET.get(model)
    sizes = [tuple(size) for size in shown]
    if detail == "full" or not sizes:
        return sizes
    fixed = 1 if editing else 0
    room = REFERENCE_MEGAPIXELS * PIXELS_PER_MEGAPIXEL
    if budget:
        used = made[0] * made[1] * (1 + fixed)
        others = len(sizes) - fixed
        if others:
            room = min(room, max(0.25 * PIXELS_PER_MEGAPIXEL, (budget * PIXELS_PER_MEGAPIXEL - used) / others))
    result = sizes[:fixed]
    for width, height in sizes[fixed:]:
        scale = (room / (width * height)) ** 0.5
        # One that fits is left as it is: the model's own encoder puts it on its grid.
        result.append((width, height) if scale >= 1 else tuple(max(32, round(side * scale / 32) * 32) for side in (width, height)))
    return result


def for_the_page():
    """What the form needs to know to grey out what a model can't do, and what it can do besides."""
    return {model: {"label": LABELS[model], "most_megapixels": MOST_MEGAPIXELS.get(model),
                    "least_megapixels": LEAST_MEGAPIXELS.get(model), "default_megapixels": DEFAULT_MEGAPIXELS.get(model), "most_written": MOST_WRITTEN.get(model),
                    "most_images": MOST_IMAGES.get(model), "image_name": IMAGE_NAMES.get(model, "image {}"),
                    "compose": model in COMPOSE_SWITCH, "most_megapixels_compose": MOST_MEGAPIXELS_COMPOSE.get(model),
                    "regions": model in REGION_EDITS, "transparent": model in TRANSPARENT}
            for model in LABELS}
