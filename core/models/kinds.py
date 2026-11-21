"""What a model family's file in core/models/ says about it. Every field but a family's label and kind may be left out."""
from typing import NamedTuple


class Family(NamedTuple):
    """A model family: how a workflow of it is recognised (core/model_families.py), and its LoRAs (core/lora_check.py)."""
    label: str
    # What it makes: "image", "video", "both" or "audio".
    kind: str
    # Load CLIP's types (CLIPLoader, DualCLIPLoader...) that load this family's text encoder.
    encoders: tuple = ()
    # Names that are this family, each a phrase whose words all appear in a file name: "hunyuan video" is
    # hunyuan_video_720p.safetensors, and not hunyuan_image.
    names: tuple = ()
    # The start of a node's type only this family has.
    nodes: tuple = ()
    # core/lora_check.py's name for it, where that differs from the family's id.
    lora: str = ""
    # A regular expression matching tensor names only this family's LoRAs (and models) have, as trainers save them.
    lora_signature: str = ""


class ImageModel(NamedTuple):
    """One image model, where its limits or prompts are its own (pipelines/image/models.py reads these)."""
    label: str
    # The model it is one with, as the Model picker lists it: an edit model's make model.
    same_as: str = ""
    # The most megapixels it makes (before any upscale); where the form starts; below which it does poorly.
    most_megapixels: float = None
    default_megapixels: float = None
    least_megapixels: float = None
    # How many prompts an LLM can write for it in one reply, where its prompts are long.
    most_written: int = None
    # How many images it takes at most, where fewer than its workflow has room for.
    most_images: int = None
    # The model's tokens a job has room for on this card, image made and images shown together, in megapixels.
    token_budget: float = None
    # What it calls the images it's given in a prompt: "<image{}>".
    image_name: str = None
    # The workflow option that makes a new picture from references rather than editing image 1.
    compose_switch: str = None
    most_megapixels_compose: float = None
    # Whether it can work on a part of an image marked in a colour (pipelines/image/regions.py).
    regions: bool = False
    # How to ask it for a transparent background, around the prompt ({}).
    transparent: str = None
    # How a workflow is known to run it (core/saved_workflows.py image_model): a node only it has; the type its text
    # encoder is loaded as; or a node that makes or edits, as it's given an image or not (this is the make model; its
    # edit model is the same id with _edit).
    node: str = None
    encoder: str = None
    make_or_edit_node: str = None


class VideoModel(NamedTuple):
    """One video model, where the panel holds it to limits of its own (pipelines/video/media.py, planner.py)."""
    # The most pixels it makes a clip of in a sensible time on this card.
    most_pixels: int = None
    # How long its clips can be, in seconds: (least, most, usual).
    clip_seconds: tuple = None
