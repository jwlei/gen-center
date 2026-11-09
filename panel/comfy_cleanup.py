"""
Keeps ComfyUI's own folders free of what this app makes (core/comfy_files.py): its uploads go after every job, and
H3's memory and the clips of runs no longer saved once nothing is running or waiting, and when the panel starts.
"""
import os
import threading

from core import comfy_files
from panel import server
from panel.server import app, job, run_queue
from pipelines.video import paths as video_paths


def _video_runs():
    try:
        return set(os.listdir(video_paths.RUNS_DIR))
    except OSError:
        return None


def _idle():
    return not job.running and not any(not item.get("later") for item in run_queue.pending())


def clean(idle_too):
    gone = comfy_files.clean_inputs()
    runs = _video_runs()
    if idle_too and runs is not None:
        gone += comfy_files.clean_idle(runs)
    if gone:
        app.logger.info("Cleared %s of this app's files from ComfyUI's folders.", gone)
    return gone


def after_job(item, outcome, state, position, film):
    """A job ended: its uploads go; and with nothing else to run, what only a run going could still use."""
    clean(_idle())


server.RECORD_HOOKS.append(after_job)


def start():
    """On starting, nothing is running yet: all of it. Called by the panel's main, not on import, so tests don't."""
    threading.Thread(target=clean, args=(True,), daemon=True).start()


server.STARTUP_HOOKS.append(start)
