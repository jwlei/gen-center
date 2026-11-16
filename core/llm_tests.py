"""
LLM comparisons: one brief, on one seed and one workflow, written into a prompt by each prompt model there is (Gemini
and every local model), one image each, as one set. Its siblings: core/lora_tests.py and core/workflow_tests.py.
"""
import json
import os

ENV = "GEN_CENTER_LLM_TEST"
# The set's prompt pill.
PILL = "All LLMs"
LLMS = ("gemini", "local")


def requested(form):
    return form.get("llm_test") not in (None, "", "0")


def variations(gemini_ready, local_models, images=0, label=None):
    """
    Each prompt model that can write this set's prompt: Gemini when it has a key, then each local model, those that
    can't see an image left out when there are images. local_models: panel.settings.local_models(). label(llm,
    local_model): the name its pill uses. [{"llm", "local_model", "label"}].
    """
    label = label or (lambda llm, model: model or llm)
    found = [{"llm": "gemini", "local_model": None, "label": label("gemini", None)}] if gemini_ready else []
    found += [{"llm": "local", "local_model": model["id"], "label": label("local", model["id"])}
              for model in local_models if not images or model.get("vision")]
    if not found:
        raise ValueError("No prompt model can write it: add a Gemini key or a local model.")
    return found


def in_env(env=None):
    raw = (os.environ if env is None else env).get(ENV)
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("The saved LLM comparison is invalid.") from error
    if not isinstance(values, list) or not values or any(
            not isinstance(value, dict) or value.get("llm") not in LLMS or not isinstance(value.get("label"), str)
            or (value["llm"] == "local") != isinstance(value.get("local_model"), str) for value in values):
        raise ValueError("The saved LLM comparison is invalid.")
    return values


def compared(shots):
    """Whether a set is an LLM comparison."""
    return any(isinstance(shot.get("llm_test"), dict) for shot in shots or [])


def pill(shots):
    """The set's prompt pill ("All LLMs"), or None."""
    return PILL if compared(shots) else None
