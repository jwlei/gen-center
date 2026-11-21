"""
Everything the panel knows about each model, one family to a file, gathered here.

    core/models/<family>.py    a family with knowledge of its own: FAMILY (how a workflow of it is known, its LoRAs),
                               and any of IMAGE_MODELS (limits, prompts), VIDEO_MODELS (sizes, clip lengths), GUIDES
                               (the guide under the workflow picker, as core/model_guide.py shows it)
    core/models/others.py      every other family: one line each, how a workflow of it is known

Adding a model: a line in others.py, or a file of its own named in FAMILY_FILES below. The modules that use these
(core/model_families.py, core/lora_check.py, core/model_guide.py, pipelines/image/models.py, pipelines/video/media.py
and planner.py) read them from here; none of them names a model.
"""
import importlib

from core.models import others
from core.models.kinds import Family, ImageModel, VideoModel  # noqa: F401, for the family files and their readers

# The families with a file of their own, in the order the panel lists them.
FAMILY_FILES = ("krea2", "qwen_image", "fibo2", "moss_image", "minimax_h3", "ltx", "wan")

FAMILIES, IMAGE_MODELS, VIDEO_MODELS, GUIDES = {}, {}, {}, {}
for _name in FAMILY_FILES:
    _module = importlib.import_module(f"core.models.{_name}")
    FAMILIES[_name] = _module.FAMILY
    IMAGE_MODELS.update(getattr(_module, "IMAGE_MODELS", {}))
    VIDEO_MODELS.update(getattr(_module, "VIDEO_MODELS", {}))
    GUIDES.update(getattr(_module, "GUIDES", {}))
for _name, _family in others.FAMILIES.items():
    if _name in FAMILIES:
        raise ValueError(f"The model family {_name} is in others.py and has a file of its own.")
    FAMILIES[_name] = _family


def lora_signatures():
    """{core/lora_check.py's family name: the tensor names only its LoRAs have}, for each family that says."""
    return {family.lora or name: family.lora_signature for name, family in FAMILIES.items() if family.lora_signature}
