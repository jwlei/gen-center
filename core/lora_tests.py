"""Deterministic LoRA comparisons shared by the image and video forms."""
import json
import os
from decimal import Decimal, InvalidOperation

from core import lora_check, workflow_options

ENV = "GEN_CENTER_LORA_TEST"


def requested(form):
    return any(form.get(key) not in (None, "", "0") for key in ("lora_strength_test", "lora_style_test"))


def variations(form, options, private=False):
    if not requested(form):
        return []
    name = next((option for option in options if option["id"] == workflow_options.LORA_NAME), None)
    strength = next((option for option in options if option["id"] == workflow_options.LORA_STRENGTH), None)
    if not name or not strength:
        raise ValueError("This workflow has no style LoRA to test.")
    # Refused here, in Generate, rather than as every image of the comparison failing once it's run.
    if name.get("problem"):
        raise ValueError(f"This workflow can't take a style LoRA: {name['problem']}")
    choices = [value for value in name["choices"] if private or not lora_check.private_lora(value)]
    if not choices:
        raise ValueError("No style LoRAs are available in this mode.")
    style = form.get("lora_style_test") not in (None, "", "0")
    selected = workflow_options._matching_lora(choices, form.get("opt_lora_name") or name["default"])
    names = choices if style else [selected]
    if any(value not in choices for value in names):
        raise ValueError("Choose an available style LoRA to test.")
    try:
        low, high = Decimal(str(strength["min"])), min(Decimal("2"), Decimal(str(strength["max"])))
        legal = Decimal(str(strength["step"]))
        if form.get("lora_strength_test") not in (None, "", "0"):
            step = Decimal(form.get("lora_test_step") or "0.1")
            if not step.is_finite() or not 0 < step <= high or step % legal:
                raise ValueError(f"LoRA test increment must be a multiple of {legal}, up to {high}.")
            values = [step * index for index in range(1, int(high // step) + 1)]
        else:
            values = [Decimal(form.get("opt_lora_strength") or strength["default"])]
        if any(not value.is_finite() or not low <= value <= high for value in values):
            raise ValueError(f"LoRA test strength must be {low}-{high}.")
    except (InvalidOperation, TypeError) as error:
        raise ValueError("LoRA test increment and strength must be valid numbers.") from error
    return [{workflow_options.LORA: "1", workflow_options.LORA_NAME: name,
             workflow_options.LORA_STRENGTH: format(value, "f")} for name in names for value in values]


def in_env(env=None):
    raw = (os.environ if env is None else env).get(ENV)
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("The saved LoRA comparison is invalid.") from error
    if not isinstance(values, list) or not values or any(
            not isinstance(value, dict) or value.get("lora") != "1" or not isinstance(value.get("lora_name"), str)
            or not isinstance(value.get("lora_strength"), str) for value in values):
        raise ValueError("The saved LoRA comparison is invalid.")
    return values


def tested(shots):
    """
    The LoRAs a comparison's images ran with, as pills say them: each file once, in the order tested, with the
    strengths it ran at ("knpv3_1_nsfw (0.5-2)"). [] for a set that isn't a comparison.
    """
    strengths = {}
    for shot in shots or []:
        test = shot.get("lora_test")
        if isinstance(test, dict) and test.get("lora_name"):
            strengths.setdefault(test["lora_name"], []).append(_strength(test))
    return [f"{workflow_options.lora_label(name)} ({_said(min(values))}" + (f"-{_said(max(values))})" if min(values) != max(values) else ")")
            for name, values in strengths.items()]


def shot_lora(shot):
    """The LoRA one comparison image ran with, as its pill says it ("knpv3_1_nsfw (0.5)"), or None."""
    test = shot.get("lora_test")
    if not isinstance(test, dict) or not test.get("lora_name"):
        return None
    return f"{workflow_options.lora_label(test['lora_name'])} ({_said(_strength(test))})"


def _strength(test):
    try:
        return Decimal(str(test.get("lora_strength") or "1"))
    except InvalidOperation:
        return Decimal("1")


def _said(value):
    return format(value.normalize(), "f")


def shots(template, values, seed):
    return [{**template, "number": index, "file": None, "seed": seed, "lora_test": dict(value),
             "title": f"{workflow_options.lora_label(value['lora_name'])} · {value['lora_strength']}"}
            for index, value in enumerate(values, 1)]
