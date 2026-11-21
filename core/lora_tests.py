"""Deterministic LoRA comparisons shared by the image and video forms."""
import json
import os
from decimal import Decimal, InvalidOperation

from core import lora_check, lora_hints, workflow_options

ENV = "GEN_CENTER_LORA_TEST"


def requested(form):
    return any(form.get(key) not in (None, "", "0") for key in ("lora_strength_test", "lora_style_test"))


def variations(form, options, private=False, prefer=lora_hints.AUTHOR):
    """
    The run settings of a LoRA comparison asked for in form, one per image. prefer: which of a LoRA's strength ranges
    a strength test runs over (core/lora_hints.py), as Settings says.
    """
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
        testing = form.get("lora_strength_test") not in (None, "", "0")
        if testing:
            step = Decimal(form.get("lora_test_step") or "0.1")
            if not step.is_finite() or not 0 < step <= high or step % legal:
                raise ValueError(f"LoRA test increment must be a multiple of {legal}, up to {high}.")
        else:
            fixed = [Decimal(form.get("opt_lora_strength") or strength["default"])]
        found = []
        for name in names:
            if testing:
                # Over its range (core/lora_hints.py: the author's or ours, as prefer says), from its bottom to its top, past which
                # it was seldom kept; from the increment up to 2 for one with none. At least its first strength, so a
                # LoRA is never left out.
                bounds = lora_hints.bounds_of(name, prefer)
                start = max(low, Decimal(str(bounds[0]))) if bounds else step
                stop = min(high, Decimal(str(bounds[1]))) if bounds else high
                values = [start + step * index for index in range(max(1, int((stop - start) // step) + 1))]
            else:
                values = fixed
            if any(not value.is_finite() or not low <= value <= high for value in values):
                raise ValueError(f"LoRA test strength must be {low}-{high}.")
            found += [{workflow_options.LORA: "1", workflow_options.LORA_NAME: name,
                       workflow_options.LORA_STRENGTH: format(value, "f")} for value in values]
    except (InvalidOperation, TypeError) as error:
        raise ValueError("LoRA test increment and strength must be valid numbers.") from error
    return found


def in_env(env=None):
    raw = (os.environ if env is None else env).get(ENV)
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("The saved LoRA comparison is invalid.") from error
    if not isinstance(values, list) or not values or any(not _valid(value) for value in values):
        raise ValueError("The saved LoRA comparison is invalid.")
    return values


def _valid(value):
    """One image's settings: a LoRA and its strength, the files it runs (core/file_tests.py), or both."""
    from core import file_tests
    if not isinstance(value, dict) or not value:
        return False
    lora = "lora" in value
    if lora and (value.get("lora") != "1" or not isinstance(value.get("lora_name"), str) or not isinstance(value.get("lora_strength"), str)):
        return False
    files = [key for key in value if key in file_tests.FILES]
    if any(not isinstance(value[key], str) or not value[key] for key in files):
        return False
    return (lora or bool(files)) and all(key in ("lora", "lora_name", "lora_strength", *file_tests.FILES) for key in value)


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


def shot_lora(shot, shots=()):
    """
    What one comparison image ran with, as its pill says it: its LoRA ("knpv3_1_nsfw (0.5)"), the files it ran
    (core/file_tests.py, "Model krea2_turbo_fp8"), or both. None for one that isn't a comparison's.
    """
    from core import file_tests
    test = shot.get("lora_test")
    if not isinstance(test, dict):
        return None
    parts = ([f"{workflow_options.lora_label(test['lora_name'])} ({_said(_strength(test))})"] if test.get("lora_name") else [])         + ([file_tests.label(test, [other.get("lora_test") for other in shots or ()])] if file_tests.label(test) else [])
    return " · ".join(parts) or None


def _strength(test):
    try:
        return Decimal(str(test.get("lora_strength") or "1"))
    except InvalidOperation:
        return Decimal("1")


def _said(value):
    return format(value.normalize(), "f")


def title_of(shot, shots=()):
    """
    A comparison image's title as it's said now, from what it ran (its LoRA and strength, its files), so one made
    before the names were short reads as a new one does; any other image's own title.
    """
    from core import file_tests
    test = shot.get("lora_test")
    if not isinstance(test, dict) or not test:
        return shot.get("title")
    tests = [other.get("lora_test") for other in shots or () if isinstance(other.get("lora_test"), dict)]
    parts = ([f"{workflow_options.lora_label(test['lora_name'])} · {test['lora_strength']}"] if test.get("lora_name") else [])         + ([file_tests.label(test, tests)] if file_tests.label(test) else [])
    return " · ".join(parts) or shot.get("title")


def shots(template, values, seed):
    from core import file_tests
    title = lambda value: " · ".join(
        ([f"{workflow_options.lora_label(value['lora_name'])} · {value['lora_strength']}"] if value.get("lora_name") else [])
        + ([file_tests.label(value, values)] if file_tests.label(value) else []))
    return [{**template, "number": index, "file": None, "seed": seed, "lora_test": dict(value), "title": title(value)}
            for index, value in enumerate(values, 1)]
