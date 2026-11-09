"""Persistent display metadata for independently retained video upscales."""
import json
import os
import tempfile

from core import workflow_options
from core.saved_workflows import shorthand
from pipelines.video.main import BUILT_IN
from pipelines.video.run_state import UPSCALED, films_of_runs, run_of_film


def sidecar(path):
    return path + ".metadata.json"


def read(path):
    try:
        with open(sidecar(path), encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"Invalid video metadata in {sidecar(path)}")
    return data


def write(path, data):
    directory = os.path.dirname(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as file:
            temporary = file.name
            json.dump(data, file, ensure_ascii=False, indent=1)
        os.replace(temporary, sidecar(path))
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def from_run(state):
    # The brief: an upscaled copy stays a sibling of what its prompt made (core/pills.py).
    return {"origin_run": state.id, "title": state.title or state.brief, "brief": state.brief,
            "model": shorthand(state.workflow, BUILT_IN), "llm": state.llm,
            "h3_mode": state.h3_mode, "h3_creativity": state.h3_creativity,
            "connection": state.connection_mode or state.start, "direct": bool(state.direct),
            "loras": workflow_options.loras_used(state.workflow, state.options, "video")}


def resolve(path, films=None):
    stored = read(path)
    if stored is not None:
        return stored
    source = path
    while UPSCALED.search(source):
        source = UPSCALED.sub(".mp4", source)
        stored = read(source)
        if stored is not None:
            return stored
    films = films_of_runs() if films is None else films
    run = run_of_film(os.path.basename(path), films)
    state = next((state for state in films.values() if state.id == run), None)
    return from_run(state) if state else None
