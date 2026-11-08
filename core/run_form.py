"""The panel's Generate form a run was queued with, handed over in AUTOGEN_FORM, so a run can be reopened as it was made."""
import json
import os

ENV = "AUTOGEN_FORM"
# Windows caps one environment variable at 32767 characters.
LIMIT = 30000


def to_env(form):
    """The form as JSON for a run to keep. A very long narration is left out: its voiced track is kept anyway."""
    text = json.dumps(form, ensure_ascii=False)
    if len(text) > LIMIT:
        text = json.dumps({name: values for name, values in form.items() if name != "narration"}, ensure_ascii=False)
    return text if len(text) <= LIMIT else "{}"


def from_env():
    """The form this run was queued with, or None when it was started from the command line."""
    try:
        form = json.loads(os.getenv(ENV) or "null")
    except ValueError:
        return None
    return form if isinstance(form, dict) else None


def flat(form):
    """{name: value} for the page: a field sent more than once keeps its last value."""
    return {name: values[-1] if isinstance(values, list) and values else values for name, values in (form or {}).items()}
