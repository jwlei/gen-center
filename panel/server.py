"""
The web panel: one server, one GPU queue, and three pipelines: Shorts, Video and Image.

Starts their jobs, queues more while one is going, streams the log, shows whether
ComfyUI is up, and lists the finished videos for playback and download, from the
desktop or a phone, at home or anywhere over Tailscale. panel/shorts.py,
panel/video.py and panel/image.py hold what is particular to each.

    python webapp.py --host 0.0.0.0 --port 8800
    (or double-click start_webapp.pyw / the "gen-center" desktop shortcut)

Set APP_PASSWORD to expose it beyond localhost. Without it the server refuses
any host but 127.0.0.1: an open instance lets anyone spend your API quota and GPU.
"""
import argparse
import copy
import gzip
import hashlib
import atexit
import json
import logging
import math
import os
import re
import shutil
import secrets
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from functools import lru_cache, wraps

import requests
import websocket
from dotenv import load_dotenv
from flask import (Flask, Response, abort, has_request_context, redirect, render_template, request,
                   send_file, session, stream_with_context, url_for)
from werkzeug.exceptions import NotFound
from werkzeug.datastructures import MultiDict

from core import batch_stop, eta_keys, explicit, lora_hints, model_guide, pills, run_form, variety, workflow_options
from core.run_checkpoint import CheckpointError, catalogue_errors
from core.lora_tests import ENV as LORA_TEST_ENV
from core.upscale_eta import UpscaleEta, is_upscale
from core.paths import LOGS_DIR, PROJECT_ROOT, SAVED_WORKFLOWS_DIR, comfyui_client_id
from core.quota import quota_summary
from core.saved_workflows import display_label, list_saved, pipeline_of
from panel import settings, tailscale
from panel.failures import (  # noqa: F401, also reached as server.<name> by the panel's tests
    AIMDO_ERROR, EXIT_ONE_ERROR, FAILURES, MOST_WHY_LINES, REACHED_COMFYUI, REFUSED, SETTINGS_REFUSED,
    TROUBLE, explain_failure, hit_aimdo, live_crash_reason, restart_reason, why_it_failed)
from panel.catalogue import CatalogueCache
from pipelines.image.paths import OUTPUT_DIR as IMAGE_OUTPUT
from pipelines.image.run_eta import RunEta as ImageEta
from pipelines.shorts.paths import OUTPUT_DIR as SHORTS_READY, UPLOADED_DIR as SHORTS_UPLOADED
from pipelines.shorts.run_eta import RunEta as ShortsEta
from pipelines.video.paths import OUTPUT_DIR as VIDEO_OUTPUT
from pipelines.video import media as video_media
from pipelines.video import planner as video_planner
from pipelines.video import comfy as video_comfy
from pipelines.video.comfy import workflow_model
from pipelines.video.run_state import UPSCALED, films_of_runs, run_of_film
from pipelines.video.run_eta import RunEta as VideoEta

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

FOLDERS = {"output": SHORTS_READY, "uploaded": SHORTS_UPLOADED, "video": VIDEO_OUTPUT, "image": IMAGE_OUTPUT}
FOLDER_PIPELINES = {"output": "shorts", "uploaded": "shorts", "video": "video", "image": "image"}
SHORTS_TIMINGS = os.path.join(LOGS_DIR, "stage_timings_shorts.json")
VIDEO_TIMINGS = os.path.join(LOGS_DIR, "stage_timings_video.json")
IMAGE_TIMINGS = os.path.join(LOGS_DIR, "stage_timings_image.json")
PROMPT_WRITER_TIMINGS = os.path.join(LOGS_DIR, "prompt_writer_timings.json")
ETAS = {"shorts": lambda argv, env: ShortsEta(argv, env, SHORTS_TIMINGS),
        "video": lambda argv, env: UpscaleEta(argv, VIDEO_TIMINGS) if is_upscale(argv) else VideoEta(argv, VIDEO_TIMINGS, env),
        "image": lambda argv, env: UpscaleEta(argv, IMAGE_TIMINGS) if is_upscale(argv) else ImageEta(argv, env, IMAGE_TIMINGS)}
# What panel/shorts.py, panel/video.py and panel/image.py each add: load_run, describe_runs, continue_run,
# discard_run, delete_video, captions and context.
PIPELINES = {}
# A phone photo or a song is well under this; the limit only stops a mistake filling the disk.
MAX_UPLOAD_BYTES = 200 * 2 ** 20
# Keeps the pipeline and nvidia-smi from flashing a console window when the
# server itself runs windowless (start_webapp.pyw).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# The Run generation at lower priority setting: what the pipeline, and ComfyUI when this launches it, start with.
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def priority_flags():
    return BELOW_NORMAL if settings.load()["low_priority"] else 0
# How long a killed process gets to disappear before it counts as surviving.
STOP_WAIT = 10
STOP_FAILED = "It could not be stopped. End it in Task Manager (python.exe)."
# start_webapp.pyw compares this with the code on disk to replace a server that
# predates an update (templates are cached and Python only loads at start).
STARTED_AT = time.time()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# What MediaPipe's native code prints to stderr while it loads, on every lip-sync
# check. Warnings and notices only; its errors (E0000, F0000) still reach the log.
NATIVE_NOISE = re.compile(r"^[WI]\d{4} \d\d:\d\d:\d\d|^WARNING: Logging before InitGoogle|^INFO: Created TensorFlow Lite")


def kill_tree(pid):
    """Kills a process and every process it started: terminate() alone would leave its ffmpeg renders running."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# What a log line is, for the page to colour and filter by: a stage, a problem, a warning, a success, ComfyUI's own, or dim.
LINE_KINDS = (("stage", re.compile(r"^(▶ Stage|=====)")), ("err", re.compile(r"^(❌|🚨)|\bError\b|Traceback")),
              ("warn", re.compile(r"^(⚠️|🛑)")), ("ok", re.compile(r"^(✅|✨|📦)")),
              ("comfy", re.compile(r"^🎛️ ComfyUI")), ("dim", re.compile(r"^(Deleted:|🧹)")))


def line_kind(text):
    text = text.strip()
    return next((kind for kind, pattern in LINE_KINDS if pattern.search(text)), "")


class PanelOwnerLock:
    """A process-wide owner for panel state and GPU work, released by the OS on exit."""

    def __init__(self, path):
        self.path = path
        self._file = None
        self._pid = None
        self._guard = threading.Lock()
        self.error = None

    def acquire(self):
        with self._guard:
            pid = os.getpid()
            if self._file is not None and self._pid == pid:
                return True
            if self._file is not None:
                # A child must not mistake an inherited descriptor for ownership.
                self._file.close()
                self._file = None
                self._pid = None
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                lock_file = open(self.path, "a+b")
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, ImportError) as error:
                try:
                    lock_file.close()
                except (UnboundLocalError, OSError):
                    pass
                self.error = (
                    f"Could not acquire the gen-center owner lock {self.path}: {error}. "
                    "Another panel or worker may own it; stop that process and verify file permissions."
                )
                return False
            self._file = lock_file
            self._pid = pid
            self.error = None
            return True

    def release(self):
        with self._guard:
            if self._file is None:
                return
            lock_file, owner_pid = self._file, self._pid
            self._file = None
            self._pid = None
            if owner_pid == os.getpid():
                try:
                    lock_file.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except (OSError, ImportError):
                    pass
            lock_file.close()


PANEL_OWNER_PATH = os.path.join(LOGS_DIR, "panel_owner.lock")
PANEL_OWNER = PanelOwnerLock(PANEL_OWNER_PATH)
atexit.register(PANEL_OWNER.release)


# Bumped when the log or a queue changes, so the status stream sends the change straight away.
_status_change = threading.Condition()
_status_version = 0


def status_changed():
    global _status_version
    with _status_change:
        _status_version += 1
        _status_change.notify_all()


def status_version():
    with _status_change:
        return _status_version


def wait_for_status_change(seen, timeout):
    """Until the status changes from version `seen`, or `timeout` seconds."""
    with _status_change:
        _status_change.wait_for(lambda: _status_version != seen, timeout)


class Job:
    """
    Tracks one process at a time. Rendering saturates the CPU and GPU, so a second
    concurrent run would only make both slower. Uploads hardly touch either, so
    they get a Job of their own and can run during a render.
    """

    def __init__(self, batches=False):
        self.lock = threading.Lock()
        # The runs' job, not the uploads': a Stop after this one it was asked for goes with the job it was asked of.
        self.batches = batches
        self.process = None
        # {"n": sequence number, "t": "HH:MM:SS", "text": ...}; the page appends by n.
        self.lines = []
        self.seq = 0
        # What the image or clip that just started should take, in seconds, for its line in the log.
        self.expected = None
        # Lines come from the pipeline's output and from ComfyUI's websocket at once.
        self._log_lock = threading.Lock()
        # The workflow file and options this run was started with, kept after it ends so it can still be looked at.
        self.workflow = None
        self.started_at = None
        self.finished_at = None
        self.returncode = None
        self.command = None
        self.progress = {}
        self.eta = None
        self.stopped = False
        self.closed = False
        self.pipeline = "shorts"

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def idle(self):
        """Past running: _drain is done with the last process too, so a new one can't get mixed up with it."""
        return self.process is None or self.finished_at is not None

    def start(self, argv, env=None, keep_log=False, pipeline="shorts"):
        with self.lock:
            if self.closed or not self.idle:
                return False
            eta = ETAS[pipeline](argv, env)
            if self.batches:
                batch_stop.clear()
            process = subprocess.Popen(
                argv,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                # Unbuffered child output, otherwise the log only appears at the end.
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(env or {})},
                creationflags=NO_WINDOW | priority_flags(),
                # Its own process group, so stop() can take ffmpeg down with it.
                start_new_session=os.name != "nt",
            )
            if not keep_log:
                self.lines = []
            self.started_at = datetime.now()
            self.first_line = self.seq  # Its own lines start after this, if the log was kept from the job before
            self.finished_at = None
            self.returncode = None
            self.command = " ".join(argv[1:])
            self.workflow = {"path": (env or {}).get("COMFYUI_WORKFLOW"), "pipeline": pipeline,
                             "options": eta_keys.options_in(argv) if pipeline == "image" else eta_keys.options_in_env(env)}
            self.progress = {}
            self.eta = eta
            self.pipeline = pipeline
            self.stopped = False
            self.process = process

        threading.Thread(target=self._drain, daemon=True).start()
        return True

    def _drain(self):
        process = self.process
        for line in process.stdout:
            line = line.rstrip()
            # ffmpeg's progress carriage-returns would flood the log.
            if not line or line.startswith("frame=") or line.startswith("[") or NATIVE_NOISE.match(line):
                continue
            entry = self.log(line)
            self.expected = None
            self._track(line)
            if self.expected is not None:
                # The log says whether it finished on time, sooner or later.
                entry["eta"] = self.expected
            # Keep memory bounded on long batches.
            if len(self.lines) > 2000:
                del self.lines[:500]
        process.wait()
        if process.returncode == 0:
            self.eta.finish()
        self.returncode = process.returncode
        self.finished_at = datetime.now()

    def log(self, text):
        with self._log_lock:
            self.seq += 1
            entry = {"n": self.seq, "t": datetime.now().strftime("%H:%M:%S"), "k": line_kind(text), "text": text}
            self.lines.append(entry)
        status_changed()
        return entry

    # Lines main.py and its modules print, turned into structured progress.
    PATTERNS = {
        "shorts": [
            ("run", re.compile(r"===== RUN (\d+)/(\d+) =====")),
            ("run_id", re.compile(r"Run folder: (run_\w+)")),
            ("stage", re.compile(r"\u25b6 Stage (\d+)/(\d+): (.+)")),
            ("scenes", re.compile(r"narration for (\d+) scenes|Generation for (\d+) scenes")),
            ("clip", re.compile(r"Clip (\d+)/(\d+) \u00b7 scene (\d+): (\d+)s ([\w-]+)")),
            ("rejected", re.compile(r"Rejected: (.*) \(attempt (\d+)/(\d+)\)")),
            ("clip_failed", re.compile(r"Scene .+ avatar clip not made; using stock footage\.")),
            ("render", re.compile(r"Processing Scene (\d+)")),
            ("upload", re.compile(r"\U0001f4fc (\d+)/(\d+): (.+)")),
        ],
        "video": [
            ("run_id", re.compile(r"Run folder: (run_\w+)")),
            ("stage", re.compile(r"\u25b6 Stage (\d+)/(\d+): (.+)")),
            ("shot", re.compile(r"Clip (\d+)/(\d+) \u00b7 (.+) \u00b7 (\d+)s")),
            ("retry", re.compile(r"(?:Rejected: |\u274c )(.*) \(attempt (\d+)/(\d+)\)")),
            ("part", re.compile(r"Preparing clip (\d+)/(\d+)")),
        ],
        "image": [
            ("run_id", re.compile(r"Run folder: (image_\w+)")),
            ("stage", re.compile(r"\u25b6 Stage (\d+)/(\d+): (.+)")),
            ("image", re.compile(r"Image (\d+)/(\d+) \u00b7 (.+)")),
            ("retry", re.compile(r"(?:Rejected: |\u274c )(.*) \(attempt (\d+)/(\d+)\)")),
        ],
    }

    # What it is doing right now, in a word or two, for the line under the progress bars.
    # A stage starts with its own; a line from inside the stage narrows it down.
    STAGE_ACTIONS = {
        "Plan": "Planning", "Prompts": "Generating prompts", "Clips": "Rendering clips", "Images": "Rendering images",
        "Topic & script": "Writing script", "Voice": "Voicing", "Stock footage": "Fetching stock footage",
        "Avatar clips": "Rendering avatar clips", "Rendering scenes": "Composing scenes", "Stitching": "Stitching",
        "Upload": "Uploading",
    }
    ACTIONS = [
        (re.compile(r"Starting the local (?:OpenH3-IR )?model"), "Starting local model"),
        (re.compile(r"OpenH3-IR: writing a brief"), "Enhancing prompt"),
        (re.compile(r"prompt enhancer is writing"), "Enhancing prompts"),
        (re.compile(r"is writing \d+ prompts?\b"), "Generating prompts"),
        (re.compile(r"Waiting for ComfyUI|ComfyUI is starting"), "Starting ComfyUI"),
        (re.compile(r"Voicing the narration|narration for \d+ scenes|Starting Audio Generation"), "Voicing narration"),
        (re.compile(r"Rendering the whole H3 Multishot take"), "Rendering take"),
        (re.compile(r"Clip \d+/\d+ ·|OpenH3-IR prompt:"), "Rendering clip"),
        (re.compile(r"Image \d+/\d+ ·"), "Rendering image"),
        (re.compile(r"Rejected: |❌ .*\(attempt \d+/\d+\)"), "Retrying"),
        (re.compile(r"Preparing clip \d+/\d+"), "Preparing clips"),
        (re.compile(r"Processing Scene \d+"), "Composing scenes"),
        (re.compile(r"H3 Infinite is stitching"), "Stitching in ComfyUI"),
        (re.compile(r"Stitching"), "Stitching"),
        (re.compile(r"Upscaling"), "Upscaling"),
        (re.compile(r"Uploading to YouTube"), "Uploading"),
    ]

    MODEL_STARTING = "Starting local model"
    MODEL_READY = re.compile(r"Local model ready")

    # Lines that start or end something the ETA times on its own (core/eta_keys.py LocalModelTimer).
    EVENTS = [
        ("model_start", re.compile(r"Starting the local (?:OpenH3-IR )?model")),
        ("model_ready", re.compile(r"Local model ready")),
        ("enhance", re.compile(r"OpenH3-IR: writing a brief")),
        ("enhanced", re.compile(r"OpenH3-IR prompt:")),
        ("planned", re.compile(r"^\s*🎞️? (?!Continuing|Fixed clip length)")),
        ("take", re.compile(r"Rendering the whole H3 Multishot take")),
    ]

    def _track(self, line):
        # When what it is doing changes, so Status can say how long it has been at it: a long step, such as OpenH3-IR
        # writing a clip's prompt from several images, otherwise looks stuck.
        before = self.progress.get("action")
        try:
            self._track_line(line)
        finally:
            if self.progress.get("action") != before:
                self.progress["action_started"] = time.time()

    def _expect(self):
        expected = getattr(self.eta, "expected", None)
        try:
            seconds = expected() if expected else None
        except Exception:  # Only for the log: never let it stop the run's tracking.
            seconds = None
        self.expected = round(seconds) if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else None

    def _track_line(self, line):
        p = self.progress
        tokens = re.fullmatch(r"Local LLM: (\d+(?:\.\d+)?) tok/s \| (\d+) total tok", line)
        if tokens:
            p["tokens"] = {"per_second": float(tokens.group(1)), "total": int(tokens.group(2))}
            return
        if line.startswith(("Local LLM: idle", "Local LLM: telemetry unavailable", "Local LLM complete:")):
            p.pop("tokens", None)
            return
        if self.eta is not None and hasattr(self.eta, "event"):
            self.eta.event(next((kind for kind, pattern in self.EVENTS if pattern.search(line)), "line"))
        action = next((label for pattern, label in self.ACTIONS if pattern.search(line)), None)
        if action == self.MODEL_STARTING and p.get("action") != self.MODEL_STARTING:
            p["action_before_model"] = p.get("action")
        if action:
            p.pop("tokens", None)
            p["action"] = action
        elif self.MODEL_READY.search(line) and p.get("action") == self.MODEL_STARTING:
            # Started: it is now doing what it was started for (writing the prompts, say), not starting any more.
            p["action"] = p.pop("action_before_model", None) or "Local model working"
        if self.pipeline == "video" and line.startswith("✅ Upscaled: "):
            p["upscaled_file"] = os.path.basename(line.removeprefix("✅ Upscaled: ").strip())
        for kind, pattern in self.PATTERNS[self.pipeline]:
            m = pattern.search(line)
            if not m:
                continue
            if kind == "run":
                p["run"] = [int(m.group(1)), int(m.group(2))]
                self.eta.video(int(m.group(1)), int(m.group(2)))
            elif kind == "run_id":
                p["run_id"] = m.group(1)
            elif kind == "stage":
                p.pop("tokens", None)
                p["stage"] = [int(m.group(1)), int(m.group(2)), m.group(3).strip()]
                p["stage_started"] = time.time()
                p.pop("detail", None)
                p["action"] = self.STAGE_ACTIONS.get(p["stage"][2], p["stage"][2])
                self.eta.stage(*p["stage"])
            elif kind == "scenes":
                p["scenes"] = int(m.group(1) or m.group(2))
                self.eta.scenes(p["scenes"])
            elif kind == "clip":
                p["detail"] = f"Clip {m.group(1)} of {m.group(2)} - scene {m.group(3)}, {m.group(4)}s {m.group(5)}"
                self.eta.clip(int(m.group(1)), int(m.group(2)), int(m.group(4)))
            elif kind == "rejected":
                self.eta.clip_rejected(int(m.group(2)), int(m.group(3)), m.group(1))
            elif kind == "clip_failed":
                self.eta.clip_failed()
            elif kind == "render":
                total = p.get("scenes")
                p["detail"] = f"Scene {m.group(1)}" + (f" of {total}" if total else "")
                self.eta.scene()
            elif kind == "shot":
                p["detail"] = f"Clip {m.group(1)} of {m.group(2)}: {m.group(3)}, {m.group(4)}s"
                self.eta.clip(int(m.group(1)), int(m.group(2)), int(m.group(4)))
                self._expect()
            elif kind == "image":
                p["detail"] = f"Image {m.group(1)} of {m.group(2)}: {m.group(3)}"
                self.eta.image(int(m.group(1)), int(m.group(2)))
                self._expect()
            elif kind == "retry":
                self.eta.clip_retry(int(m.group(2)), int(m.group(3)), m.group(1))
            elif kind == "part":
                p["detail"] = f"Preparing clip {m.group(1)} of {m.group(2)}"
            elif kind == "upload":
                p["upload"] = [int(m.group(1)), int(m.group(2)), m.group(3).strip()]
            return

    def stop(self, failed=False):
        """
        Kills the process and everything it started, and waits for it to go.
        False if nothing was running, or if it survived: then `running` stays True.
        """
        with self.lock:
            if not self.running:
                return False
            self.stopped = not failed
            pid = self.process.pid
            kill_tree(pid)
            try:
                self.process.wait(timeout=STOP_WAIT)
            except subprocess.TimeoutExpired:
                self.stopped = False
                self.log(f"⚠️ Could not stop process {pid}.")
                return False
            self.log("Generation stopped after a fatal ComfyUI error." if failed else "🛑 Stopped by user.")
        return True

    def close(self):
        """Nothing starts from here on, so a job can't slip in while the server shuts down."""
        with self.lock:
            self.closed = True

    @property
    def uploading(self):
        """In a run's own Upload step, when its video sits in Ready with no topic recorded yet."""
        return self.running and self.progress.get("stage", [None, None, None])[2] == "Upload"

    def snapshot(self):
        return {
            "running": self.running,
            "lines": list(self.lines),
            "returncode": self.returncode,
            "stopped": self.stopped,
            "command": self.command,
            "pipeline": self.pipeline,
            "started_at": self.started_at.strftime("%H:%M:%S") if self.started_at else None,
            "elapsed": int(((self.finished_at or datetime.now()) - self.started_at).total_seconds()) if self.started_at else 0,
            "progress": {**self.progress,
                         "stage_elapsed": int(time.time() - self.progress["stage_started"])
                         if "stage_started" in self.progress else 0,
                         "action_elapsed": int(time.time() - self.progress["action_started"])
                         if "action_started" in self.progress else None,
                         "eta": self.eta.estimate() if self.eta and self.running else None},
        }


job = Job(batches=True)
uploads = Job()


# Called as a job ends, with (item, outcome, its run's state, the position it made, the film it made): what other parts
# of the panel do then (panel/collections.py puts an upscale of an item in a collection in the same one).
RECORD_HOOKS = []
# Called with the status as it is built, after NSFW tags: panel/collections.py marks what is in a collection.
STATUS_HOOKS = []
# Called once as the panel starts serving (main), not on import: panel/comfy_cleanup.py clears ComfyUI's folders.
STARTUP_HOOKS = []


RUN_COUNT = re.compile(r"^(\d+ (?:images?|videos?|clips?|films?))(?::\s*(.*))?$", re.S)


def new_run_line(item):
    """
    The log's line as the next job in the queue starts: "===== New run, 20 images ===== its title", which the page
    shows as two lines. How many comes from its label ("20 images: …") or the start of its detail ("1:00 film · …").
    """
    label = (item.get("label") or "").strip()
    count = RUN_COUNT.match(label)
    if count:
        what, title = count.group(1), (count.group(2) or "").strip()
    else:
        first = (item.get("detail") or "").split(" · ")[0].strip()
        what, title = (first if re.search(r"\d", first) else ""), label
    return f"===== New run{', ' + what if what else ''} ===== {title}".rstrip()


class JobQueue:
    """
    The jobs waiting for a Job, oldest first, each keeping the options it was
    queued with. A failed job doesn't stop the ones after it, as in a batch.
    Stop does: pressing it means nothing should start by itself, so what is
    queued waits for Resume. Pending jobs stay until the user starts or removes
    them. A versioned `<queue>_state.json` ledger beside the legacy queue path
    brings waiting work back after a Shut down or crash, on hold for the same reason.
    """

    KEPT_RESULTS = 20  # Finished keeps the last twenty, saved beside the queue so they outlast a restart
    def __init__(self, job, prepare, blocked=lambda: False, path=None):
        self.job = job
        self.prepare = prepare  # Last step before a job starts; returns why it can't run, or None.
        self.blocked = blocked
        self.path = path
        self.lock = threading.RLock()  # snapshot_with_job() holds it around snapshot()
        self.items = []
        self.current = None
        self.results = []
        self.held = False
        self.next_id = 1
        self.persistence_error = None
        self._needs_migration = False
        self.watcher = None
        self._restore()

    @property
    def results_path(self):
        """The legacy Finished file path retained for migration and compatibility."""
        return os.path.splitext(self.path)[0] + "_finished.json" if self.path else None

    @property
    def ledger_path(self):
        """The `<queue>_state.json` atomic versioned snapshot for all persisted state."""
        return os.path.splitext(self.path)[0] + "_state.json" if self.path else None

    @staticmethod
    def _validate_item(item, require_id=True):
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise ValueError("each queued item must be an object with a label")
        if require_id and (not isinstance(item.get("id"), int) or isinstance(item.get("id"), bool) or item["id"] < 1):
            raise ValueError("each queued item must have a positive integer id")
        argv = item.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("each queued item must have a non-empty argv list of strings")

    @classmethod
    def _validate_results(cls, results):
        if not isinstance(results, list):
            raise ValueError("results must be a list")
        for result in results:
            if not isinstance(result, dict) or not isinstance(result.get("label"), str):
                raise ValueError("each result must be an object with a label")
            job_id = result.get("job_id")
            if job_id is not None and (not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1):
                raise ValueError("result job ids must be positive integers")
            if result.get("job") is not None:
                cls._validate_item(result["job"], require_id=False)

    @classmethod
    def _validate_ledger(cls, ledger):
        if (not isinstance(ledger, dict) or not isinstance(ledger.get("version"), int)
                or isinstance(ledger.get("version"), bool) or ledger["version"] != 1):
            raise ValueError("the ledger must be a version 1 object")
        items = ledger.get("items")
        current = ledger.get("current")
        results = ledger.get("results")
        next_id = ledger.get("next_id")
        held = ledger.get("held")
        if not isinstance(items, list):
            raise ValueError("items must be a list")
        for item in items:
            cls._validate_item(item)
        if current is not None:
            cls._validate_item(current)
        cls._validate_results(results)
        if not isinstance(next_id, int) or isinstance(next_id, bool) or next_id < 1:
            raise ValueError("next_id must be a positive integer")
        if not isinstance(held, bool):
            raise ValueError("held must be a boolean")
        identifiers = [item["id"] for item in items]
        if current:
            identifiers.append(current["id"])
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("queued item ids must be unique")
        saved_ids = identifiers + [r["job_id"] for r in results if r.get("job_id") is not None]
        if len(saved_ids) != len(set(saved_ids)):
            places = {}
            for where, ids in (("queue", [item["id"] for item in items]), ("current", [current["id"]] if current else []),
                               ("Finished", [r["job_id"] for r in results if r.get("job_id") is not None])):
                for job_id in ids:
                    places.setdefault(job_id, []).append(where)
            repeated = {job_id: where for job_id, where in places.items() if len(where) > 1}
            raise ValueError(f"job ids must be unique across the queue and Finished (repeated: {repeated})")
        if saved_ids and next_id <= max(saved_ids):
            raise ValueError("next_id must be greater than every saved job id")

    def _persistence_failed(self, message):
        if self.persistence_error is None:
            self.persistence_error = message
            self.held = True
            self.job.log(
                f"⚠️ Queue persistence is blocked: {message} "
                "The saved files were left untouched; queued work will not run. "
                "Restore or repair the named file, then restart the panel."
            )

    def _restore(self):
        if not self.path:
            return
        if os.path.exists(self.ledger_path):
            try:
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    ledger = json.load(f)
                self._validate_ledger(ledger)
                self.items = ledger["items"]
                self.current = ledger["current"]
                self.results = ledger["results"][-self.KEPT_RESULTS:]
                self.next_id = ledger["next_id"]
                self.held = bool(ledger["held"] or self.items or self.current)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self._persistence_failed(f"could not read {self.ledger_path}: {error}")
                return
            if self.current is not None:
                interrupted = {**self.current, "waited": True, "interrupted": True}
                self.current = None
                self.items.insert(0, interrupted)
                self.held = True
                self._needs_migration = True
            return

        # Legacy queue and Finished files remain in place as a recovery copy.
        source = self.path
        try:
            queue_exists = os.path.exists(self.path)
            results_exists = os.path.exists(self.results_path)
            if queue_exists:
                source = self.path
                with open(self.path, "r", encoding="utf-8") as f:
                    items = json.load(f)
                if not isinstance(items, list):
                    raise ValueError("the legacy queue must be a list")
                for item in items:
                    self._validate_item(item)
                items = [{**item, "waited": True} for item in items]
            else:
                items = []
            if results_exists:
                source = self.results_path
                with open(self.results_path, "r", encoding="utf-8") as f:
                    results = json.load(f)
                self._validate_results(results)
            else:
                results = []
            identifiers = [item["id"] for item in items]
            result_ids = [r["job_id"] for r in results if r.get("job_id") is not None]
            self.items = items
            self.results = results[-self.KEPT_RESULTS:]
            self.next_id = max(identifiers + result_ids, default=0) + 1
            self.held = bool(items)
            self._needs_migration = queue_exists or results_exists
        except (OSError, ValueError, TypeError, KeyError) as error:
            self._persistence_failed(f"could not migrate {source}: {error}")

    def _save_results(self):
        return self._save_snapshot(allow_closed=True)

    def forget(self, run_id=None, film=None):
        """Takes out of Finished what was deleted from Output: the lines for that run or that film."""
        with self.lock:
            kept = [result for result in self.results
                    if not ((run_id and result.get("run_id") == run_id) or (film and result.get("film") == film))]
            if len(kept) != len(self.results):
                self.results = kept
                self._save_results()

    def clear_results(self, job_ids=None):
        """Clears the selected results, or all when no selection is given. Their files stay."""
        with self.lock:
            self.results = [] if job_ids is None else [r for r in self.results if r.get("job_id") not in job_ids]
            self._save_results()

    def forget_result(self, job_id):
        """Takes one job off Finished (a swipe). What it made stays. Returns whether it was there."""
        with self.lock:
            kept = [result for result in self.results if result.get("job_id") != job_id]
            forgotten = len(kept) != len(self.results)
            if forgotten:
                self.results = kept
                self._save_results()
            return forgotten

    def _save(self):
        # Once closed, the ledger keeps what was queued at Shut down.
        if not self.path or self.job.closed:
            return not self.job.closed
        return self._save_snapshot()

    def _activate(self):
        if self.persistence_error:
            return False
        if not PANEL_OWNER.acquire():
            self._persistence_failed(PANEL_OWNER.error or f"could not acquire ownership of {PANEL_OWNER.path}")
            return False
        if self._needs_migration:
            return self._write_ledger()
        return True

    def _write_ledger(self):
        saved_ids = [item["id"] for item in self.items]
        if self.current:
            saved_ids.append(self.current["id"])
        saved_ids.extend(result["job_id"] for result in self.results if result.get("job_id") is not None)
        if saved_ids:
            self.next_id = max(self.next_id, max(saved_ids) + 1)
        ledger = {"version": 1, "items": self.items, "current": self.current,
                  "results": self.results, "next_id": self.next_id, "held": self.held}
        temporary = None
        try:
            self._validate_ledger(ledger)
            directory = os.path.dirname(self.ledger_path) or "."
            os.makedirs(directory, exist_ok=True)
            for _ in range(10):
                temporary = f"{self.ledger_path}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp"
                try:
                    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    break
                except FileExistsError:
                    continue
            else:
                raise OSError("could not create a unique ledger staging file")
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump(ledger, f, ensure_ascii=False, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.ledger_path)
            temporary = None
            if os.name != "nt":
                try:
                    folder_fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(folder_fd)
                    finally:
                        os.close(folder_fd)
                except OSError:
                    pass
            self._needs_migration = False
            return True
        except (OSError, TypeError, ValueError) as error:
            self._persistence_failed(f"could not write {self.ledger_path}: {error}")
            return False
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass

    def _save_snapshot(self, allow_closed=False):
        status_changed()
        if not self.path:
            return True
        if not allow_closed and self.job.closed:
            return False
        with self.lock:
            if not self._activate():
                return False
            return self._write_ledger()

    def _ensure_watcher(self):
        # Here and not at import: gunicorn forks after importing, and threads don't survive that.
        if not self.watcher:
            self.watcher = threading.Thread(target=self._watch, daemon=True)
            self.watcher.start()

    def add(self, item):
        """Starts the job if nothing is ahead of it, otherwise queues it. Returns True if it is queued."""
        edit_id = request.form.get("queue_edit_id", type=int) if has_request_context() else None
        edit_token = request.form.get("queue_edit_token") if edit_id else None
        # Generate's "Add to pending": it waits in the queue until it's started.
        generating = has_request_context() and request.path.startswith("/generate/")
        if (generating and request.form.get("start_later")) or (has_request_context() and request.args.get("later")):
            item["later"] = True
        # Generate's "Add to top of queue", or Pending's arrow on a stopped run: ahead of everything already waiting.
        asked_top = has_request_context() and ((generating and request.form.get("queue_top")) or request.args.get("top"))
        to_top = not item.get("later") and bool(asked_top)
        # A stopped run sent on from Pending (?pending=1): only its top-of-queue arrow starts it with nothing running.
        # Retry in Finished and Make them after a review start it as before.
        from_pending = has_request_context() and bool(request.args.get("pending"))
        # New creations only: an upscale or continuation of something made before keeps that one's tag.
        if self is run_queue and private_mode() and item.get("pipeline") in ("image", "video") and (not item.get("resume") or item.get("new_run")):
            item["private"] = True
        with self.lock:
            self._ensure_watcher()
            if edit_id is not None:
                old = next((entry for entry in self.items if entry["id"] == edit_id), None)
                if not old or not edit_token or old.get("edit_token") != edit_token or old.get("pipeline") != item.get("pipeline"):
                    item["error"] = "That queued job changed or is no longer being edited. Open its setup again."
                    return True
                self.items.remove(old)
                if old.get("private"):
                    item["private"] = True
                item["id"] = edit_id
                item["waited"] = True
                # A continued run's setup reopened as a new run can go to Pending (the end) or the top; a plain edit keeps its place at the front.
                self.items.insert(len(self.items) if item.get("later") else 0, item)
                if generating and to_top and not self.job.running:
                    self.held = True
                self._save()
                self._advance()
                return item in self.items
            if self.current and self.job.idle:
                self._finish_current()
            item["id"] = self.next_id
            self.next_id += 1
            hold_top = generating and to_top and not self.job.running
            if hold_top:
                self.held = True
            idle = self.job.idle and not self.current
            if from_pending and not to_top and idle and not item.get("later"):
                # Into the queue, not started: it waits there for Resume.
                self.held = True
            # On hold and nothing running: this one starts now, and what was waiting stays on hold.
            elif self.held and not hold_top and idle and not item.get("later"):
                if not self.blocked():
                    self.held = bool(self.items)
                    item["waited"] = False
                    self._start(item)
                    return False
                # Something holds up starting for a moment (ComfyUI being cleared after the last run, or restarted, or
                # the prompt writer busy): first in line, started as soon as it's free (_advance). Before, it joined the
                # held queue and never started, though Generate had said it would.
                item["start_next"] = True
                self.items.insert(0, item)
                item["waited"] = True
                self._save()
                return True
            # Ahead of those waiting to be started, which stay at the end.
            at = len(self.items) if item.get("later") else 0 if to_top else next((i for i, waiting in enumerate(self.items) if waiting.get("later")), len(self.items))
            self.items.insert(at, item)
            if self.job is job and self.job.running and batch_stop.requested():
                self.held = True
            self._advance()
            item["waited"] = item in self.items
            self._save()
            return item["waited"]

    def _watch(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                self._advance()

    def _advance(self):
        if self.persistence_error:
            return
        if self is run_queue and self.current and self.job.running and live_crash_reason(self.job):
            # A crashed sampler can leave the pipeline waiting forever instead of exiting.
            if not self.job.stop(failed=True):
                return
        # Made in private mode: its run is tagged NSFW as soon as it has one, so it never shows outside the NSFW filter.
        if self.current and self.current.get("private") and not self.current.get("private_tagged"):
            run_id = (self.job.progress or {}).get("run_id") or self.current.get("resume")
            if run_id and tag_run_nsfw(self.current.get("pipeline"), run_id):
                self.current["private_tagged"] = True
        if self.current and self.job.idle:
            self._finish_current()
        if not self.items:
            self.held = False
        elif self.job.idle and self.held and self.items[0].get("start_next"):
            # Generated while the queue was held and idle, but something held up starting it: now it goes, on its own.
            if self.blocked():
                return
            item = self.items.pop(0)
            item.pop("start_next", None)
            self.held = bool(self.items)
            self._start(item)
        elif self.job.idle and not self.held:
            # The first that may start: one waiting to be started lets those behind it go first.
            ready = next((i for i, waiting in enumerate(self.items) if not waiting.get("later")), None)
            # Asked only with one ready: being asked closes the prompt writer's warm model (warm_writer_in_the_way).
            if ready is None or self.blocked():
                return
            item = self.items.pop(ready)
            self._start(item)

    def _finish_current(self):
        global _comfy_freeing
        item, self.current = self.current, None
        # Before the next job can start: what this one loaded would otherwise stay in memory under it.
        if self.job.batches:
            ahead = None if self.held else next((waiting for waiting in self.items if not waiting.get("later")), None)
            if frees_comfyui(item, ahead):
                # Not under the queue's lock: a busy ComfyUI can take seconds to answer, and the page's status waits on it.
                _comfy_freeing = True
                threading.Thread(target=free_comfyui, daemon=True).start()
        code = self.job.returncode
        # Noted before _record: its hooks can start the next job, whose progress would replace this run's id.
        if self.job.stopped:
            note_outcome(self.job, item, STOPPED)
            self._record(item, "stopped", save=False)
            self._keep_unsaved_stop(item, save=False)
            self._save()
        elif code == 0:
            if self is run_queue and item.get("pipeline") == "video":
                run_id = (self.job.progress or {}).get("run_id") or item.get("resume")
                state = PIPELINES["video"].load_run(run_id) if run_id else None
                if state and state.prompt_warning_pending:
                    argv = PIPELINES["video"].resume_argv(state)
                    if item.get("first_only"):
                        argv += ["--first-only"]
                    waiting = {**item, "argv": argv, "resume": state.id, "later": True, "waited": True,
                               "plan_only": False, "prompt_warnings": state.prompt_warnings,
                               "estimate": PIPELINES["video"].estimate(argv, item.get("env") or {})}
                    self.items.append(waiting)
                    self._save()
                    _runs_cache["at"] = 0.0
                    return
            note_outcome(self.job, item, NOT_RENDERED if item.get("plan_only") else FIRST_ONLY if item.get("first_only") else None)
            self._record(item, "done")
        else:
            reason = restart_reason(self.job, code) if self is run_queue else None
            if reason:
                if not item.get("aimdo_retried"):
                    self._retry_after_restart(item, reason)
                    return
                self.job.log(f"❌ {reason[0].upper()}{reason[1:]} came again after a restart: it goes to Failed, and "
                             "ComfyUI restarts once more for what comes next.")
                restart_comfyui_in_background()
            # In plain words, with what to do, when it's a failure we know; the run's own lines under it.
            plain, said = explain_failure(self.job, code)
            note_outcome(self.job, item, {"outcome": "failed", "why": f"{plain}\n\nFrom its log:\n{said}" if plain else said})
            self._record(item, "failed", plain or f"exit {code}")
            if self.items:
                self.job.log(f"❌ {item['label']} failed (exit {code}).")

    def _keep_unsaved_stop(self, item, save=True):
        """A run stopped before it saved anything has no stopped run to continue: its settings go back to Pending instead."""
        if self is not run_queue or not self.results or self.results[-1].get("run_id") or self.results[-1].get("job_id") != item.get("id"):
            return
        self.results.pop()
        item_id = self.next_id
        self.next_id += 1
        self.items.append({**{key: value for key, value in item.items() if key not in self.TRANSIENT_KEYS},
                           "id": item_id, "later": True, "waited": True})
        if save:
            self._save()
        _runs_cache["at"] = 0.0

    def _retry_after_restart(self, item, reason):
        """
        First failure of a kind that ComfyUI is restarted for (restart_reason): ComfyUI is force-restarted and the job
        goes first in line, to continue its saved run when it made one (its prompts are kept) or start over when it didn't.
        """
        retry = {**item, "aimdo_retried": True, "waited": True}
        retry.pop("later", None)
        run_id = (self.job.progress or {}).get("run_id")
        pipeline = PIPELINES.get(item.get("pipeline"))
        if run_id and not item.get("resume") and pipeline and hasattr(pipeline, "resume_argv"):
            state = pipeline.load_run(run_id)
            if state:
                argv = pipeline.resume_argv(state)
                # A preview run stays one: continuing would otherwise make every clip.
                retry["argv"] = argv + ["--first-only"] if "--first-only" in (item.get("argv") or []) else argv
                retry["resume"] = run_id
        restarting = restart_comfyui_in_background()
        self.job.log(f"⚠️ The run failed ({reason}): "
                     + ("restarting ComfyUI, then trying once more." if restarting else "trying once more."))
        self.items.insert(0, retry)
        self._save()

    def _start(self, item):
        if self.persistence_error:
            if item not in self.items and self.current is not item:
                self.items.insert(0, item)
            self.held = True
            return False
        self.current = item
        if not self._activate():
            self.current = None
            if item not in self.items:
                self.items.insert(0, item)
            self.held = True
            return False
        if item.get("waited"):
            self.job.log(new_run_line(item))
        # Record ownership before preflight or process creation. A crash at any
        # point after this snapshot restores the job on hold instead of losing it.
        if not self._save():
            self.current = None
            if item not in self.items:
                self.items.insert(0, item)
            self.held = True
            return False
        try:
            error = self.prepare(item)
            if not error and not self._save():
                self.current = None
                if item not in self.items:
                    self.items.insert(0, item)
                self.held = True
                return False
            # Made in Private mode: told to the job, whose titling keeps an NSFW prompt from Gemini (core/titles.py).
            env = {**(item.get("env") or {}), "GEN_CENTER_PRIVATE": "1"} if item.get("private") else item.get("env")
            # A job that waited adds to the log, so the one before it can still be read.
            if not error and self.job.start(item["argv"], env, keep_log=item.get("waited", False), pipeline=item.get("pipeline", "shorts")):
                return
            error = error or "Another job took its place."  # A setup check, started in the moment between two jobs
        except Exception as e:  # One bad job must not take the watcher thread, and the queue, down with it
            error = str(e)
        self.current = None
        item["error"] = error
        self.job.log(f"⚠️ Skipped {item['label']}: {error}")
        self._record(item, "skipped", error)
        return False

    def _record(self, item, outcome, note=None, save=True):
        notify_ended(item, outcome, note)
        run_id = ((self.job.progress or {}).get("run_id") or item.get("resume")) if outcome != "skipped" and self is run_queue else None
        state = PIPELINES[item["pipeline"]].load_run(run_id) if run_id and item.get("pipeline") in PIPELINES else None
        film = os.path.basename(state.final) if state and getattr(state, "final", None) else None
        if not state or (item.get("pipeline") in ("image", "video") and not state.shots):
            run_id = None
        argv = item.get("argv") or []
        if outcome == "done" and "pipelines.video.upscale" in argv:
            film = (self.job.progress or {}).get("upscaled_file")
        position = None
        if outcome == "done" and "pipelines.image.upscale" in argv and "--image" in argv[:-1] and argv[argv.index("--image") + 1].isdigit():
            position = int(argv[argv.index("--image") + 1]) + 1
        result = {"label": item["label"], "outcome": outcome, "note": note, "pipeline": item.get("pipeline"),
                  "run_id": run_id, "film": film, "position": position, "job_id": item.get("id"),
                  "at": datetime.now().strftime("%H:%M"), "t": time.time()}
        if not run_id and item.get("private"):
            result["private"] = True
        # Failed before a run was saved (a planning error, ComfyUI gone): the job itself is kept, so its settings can
        # go back to Pending instead of being lost with it.
        if outcome == "failed" and not run_id and self is run_queue:
            result["job"] = {key: value for key, value in item.items() if key not in self.TRANSIENT_KEYS}
        for hook in RECORD_HOOKS:
            try:
                hook(item, outcome, state, position, film)
            except Exception as e:  # One part of the panel failing must not lose the job's result
                app.logger.error("A job's end could not be followed up: %s", e)
        self.results.append(result)
        del self.results[:-self.KEPT_RESULTS]
        if save:
            self._save_results()

    # What a job picks up while it waits or runs, and that a recovered copy must start without.
    TRANSIENT_KEYS = ("id", "waited", "queued_at", "error", "later", "edit_token", "edit_from_queue",
                      "aimdo_retried", "private_tagged")

    def recoverable(self):
        """The failed jobs that can still go back to Pending: their inputs must outlast the cleanup of old uploads."""
        with self.lock:
            return [result["job"] for result in self.results if result.get("job")]

    def requeue_failure(self, job_id):
        """
        Puts a failed job that left no saved run back in Pending, with the settings it had, to edit or start again.
        Returns its id in Pending, or None if there was none to put back.
        """
        with self.lock:
            result = next((result for result in self.results if result.get("job_id") == job_id
                           and result.get("outcome") == "failed" and not result.get("run_id") and result.get("job")), None)
            if not result:
                return None
            self.results.remove(result)
            self._ensure_watcher()
            # A new number: the old one names the failure, which is gone now.
            item_id = self.next_id
            self.next_id += 1
            self.items.append({**result["job"], "id": item_id, "later": True, "waited": True})
            self._save()
            self._save_results()
            self._advance()
            return item_id

    def dismiss_failure(self, job_id):
        """Forgets a failure that has no saved run to retry. Returns whether there was one."""
        with self.lock:
            kept = [result for result in self.results
                    if not (result["job_id"] == job_id and result["outcome"] == "failed" and not result["run_id"])]
            dismissed = len(kept) != len(self.results)
            self.results = kept
            if dismissed:
                self._save_results()
            return dismissed

    def hold(self):
        with self.lock:
            self.held = bool(self.items)
            self._save()

    def resume(self):
        with self.lock:
            self._ensure_watcher()
            if not self._activate():
                self.held = True
                return
            self.held = False
            if not self._save():
                self.held = True
                return
        # Starting the next job can take seconds (ComfyUI checks): not while the page's request waits on it.
        threading.Thread(target=self._advance_locked, daemon=True).start()

    def _advance_locked(self):
        with self.lock:
            self._advance()

    def start(self, item_id, top=False):
        """
        Puts a pending job in the queue, at its end (the top: ahead of what waits there): it starts when the queue gets
        to it, and waits while the queue is on hold. With nothing running, only the top starts it, now, and what else
        is waiting keeps its hold; put at the end, it waits for Resume, as the queue goes on hold.
        """
        with self.lock:
            item = next((item for item in self.items if item["id"] == item_id), None)
            if not item:
                return False
            if item.get("edit_token"):
                return False
            self._approve_prompt_warning(item)
            item.pop("later", None)
            self.items.remove(item)
            idle = self.job.idle and not self.current
            if top and idle and self.held:
                if not self.blocked():
                    self.held = any(not waiting.get("later") for waiting in self.items)
                    self._start(item)
                    self._save()
                    return True
                item["start_next"] = True  # Started as soon as what holds it up is done (_advance)
            elif not top and idle:
                self.held = True
            # Ahead of those still pending, which stay at the end.
            at = 0 if top else next((i for i, waiting in enumerate(self.items) if waiting.get("later")), len(self.items))
            self.items.insert(at, item)
            self._advance()
            self._save()
            return True

    def pause(self, item_id):
        """Takes a waiting job out of the active queue: it goes to the end, waiting to be started."""
        with self.lock:
            item = next((item for item in self.items if item["id"] == item_id), None)
            if not item:
                return False
            item["later"] = True
            self.items.remove(item)
            self.items.append(item)
            self._advance()
            self._save()
            return True

    def run_now(self, item_id):
        """Runs one waiting job while nothing is running, ahead of the rest: a paused queue stays paused."""
        with self.lock:
            if self.current and self.job.idle:
                self._finish_current()
            if not self.job.idle or self.current or self.blocked():
                return "not_ready", None
            item = next((item for item in self.items if item["id"] == item_id), None)
            if not item:
                return "not_found", None
            if item.get("edit_token"):
                return "not_ready", None
            self._approve_prompt_warning(item)
            self.items.remove(item)
            item.pop("later", None)
            self.held = self.held and bool(self.items)
            self._start(item)
            if self.current is item:
                return "started", None
            return "failed", item.get("error", "Could not start the queued job.")

    def _approve_prompt_warning(self, item):
        if self is run_queue and item.get("pipeline") == "video" and item.get("resume"):
            state = PIPELINES["video"].load_run(item["resume"])
            if state and state.prompt_warning_pending:
                state.approve_prompts()
            item.pop("prompt_warnings", None)

    def reorder(self, ids):
        """
        Puts the waiting jobs in the order of these ids, as dragged on the page. One added since the page was drawn
        isn't in it, and stays where it was among the rest. Returns whether the order changed.
        """
        with self.lock:
            by_id = {item["id"]: item for item in self.items}
            wanted = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
            slots = iter(wanted)
            placed = {id(item) for item in wanted}
            order = [next(slots) if id(item) in placed else item for item in self.items]
            changed = order != self.items
            self.items = order
            self._advance()
            self._save()
            return changed

    def remove(self, item_id):
        with self.lock:
            kept = [item for item in self.items if item["id"] != item_id]
            removed = len(kept) != len(self.items)
            self.items = kept
            self._advance()
            self._save()
            return removed

    def close(self):
        """Lets nothing start again, and leaves what is waiting in the file. The running job is the caller's to stop."""
        with self.lock:
            self._save()
            self.job.close()
            self.items = []
            self.held = False

    def pending(self):
        """Every job not finished yet, the running one included."""
        with self.lock:
            self._advance()
            return ([self.current] if self.current else []) + list(self.items)

    def snapshot_with_job(self):
        """
        The job and this queue at one moment. Read apart, a status could fall between a job ending and the next one
        starting: the old job done and the queue already empty, so nothing at all for a poll.
        """
        with self.lock:
            return self.job.snapshot(), self.snapshot()

    def snapshot(self):
        with self.lock:
            self._advance()
            for item in ([self.current] if self.current else []) + list(self.items):
                described_continuation(item)
                named_comparison(item)
            argv_flag = lambda item, name: (item.get("argv") or [])[(item.get("argv") or []).index(name) + 1] \
                if name in (item.get("argv") or [])[:-1] else None
            public = lambda item: {**{key: item.get(key) for key in ("id", "label", "detail", "estimate", "videos", "pipeline", "later", "resume", "prompt_warnings")},
                                   # What tells whether it is NSFW (_apply_nsfw): made in Private mode, or the run or film it works on.
                                   "private": bool(item.get("private")), "film": argv_flag(item, "--film"),
                                   "editing": bool(item.get("edit_token")),
                                   "continuation": bool(item.get("resume") and "--redo" not in (item.get("argv") or [])
                                                        and not upscale_queue_settings(item)),
                                   "facts": run_facts(item)}
            # A kept job's command line and environment stay on the server: the page only learns it can be recovered.
            shown = lambda result: {**{key: value for key, value in result.items() if key != "job"},
                                    "recoverable": bool(result.get("job"))}
            return {"items": [public(item) for item in self.items],
                    "current": public(self.current) if self.current else None,
                    "results": [shown(result) for result in self.results],
                    "held": self.held}


def named_comparison(item):
    """An image LoRA comparison queued while its box said "exact prompt", said now as a new one is: "LoRA comparison"."""
    if item.get("pipeline") == "image" and LORA_TEST_ENV in (item.get("env") or {}) and " · exact prompt" in str(item.get("detail") or ""):
        item["detail"] = item["detail"].replace(" · exact prompt", " · LoRA comparison", 1)


OLD_CONTINUATION = re.compile(r"^(Continue|Redo image (\d+)|Redo from shot (\d+))$")


def described_continuation(item):
    """
    A saved run queued to continue before its queue box said what it makes ("Continue", "Redo image 3"), said now as
    a new one is, from the run: once, then kept with the job.
    """
    old = OLD_CONTINUATION.match(str(item.get("detail") or ""))
    describe = getattr(PIPELINES.get(item.get("pipeline")), "continued_detail", None)
    if not old or not item.get("resume") or not describe:
        return
    try:
        state = PIPELINES[item["pipeline"]].load_run(item["resume"])
    except Exception:  # The queue is drawn every poll: one unreadable run must not stop it
        state = None
    if state:
        redo = old.group(2) or old.group(3)
        item["detail"] = describe(state, int(redo) if redo else None)


def item_upscale(item):
    """
    The upscale a queued job renders with, as Output's pill says it ("SeedVR2, denoise 0.1", "Latent, Fast, 1.5 MP"),
    or None: an image set's from its --option flags, a film's from COMFYUI_OPTIONS, a continuation's from its saved run.
    An upscale job (Upscale in the viewer) is one already, and says so itself.
    """
    pipeline, argv, env = item.get("pipeline"), item.get("argv") or [], item.get("env") or {}
    if pipeline not in ("image", "video") or upscale_queue_settings(item):
        return None
    if pipeline == "image":
        options = dict(argv[i + 1].split("=", 1) for i, value in enumerate(argv[:-1]) if value == "--option" and "=" in argv[i + 1])
    else:
        try:
            options = json.loads(env.get("COMFYUI_OPTIONS") or "{}")
        except ValueError:
            options = {}
    if not options and item.get("resume"):
        try:
            state = PIPELINES[pipeline].load_run(item["resume"])
        except Exception:  # The queue is drawn every poll: one unreadable run must not stop it
            state = None
        options = getattr(state, "options", None) or {}
    if not isinstance(options, dict):
        return None
    return pills.image_upscale_description(options) if pipeline == "image" else pills.latent_description(options)


def run_facts(item):
    """What a run's title opens on: the workflow it renders with and the size it makes, as its options say."""
    argv, env = item.get("argv") or [], item.get("env") or {}
    flag = lambda name: argv[argv.index(name) + 1] if name in argv[:-1] else None
    count = flag("--count" if item.get("pipeline") == "image" else "--runs" if item.get("pipeline") == "shorts" else "")
    workflow = env.get("COMFYUI_WORKFLOW")
    size = item.get("resolution") or flag("--size") or env.get("AVATAR_SIZE")
    if not size and item.get("resume") and item.get("pipeline") in ("image", "video") and not upscale_queue_settings(item):
        state = PIPELINES[item["pipeline"]].load_run(item["resume"])
        if state and getattr(state, "width", None) and getattr(state, "height", None):
            size = f"{state.width}x{state.height}"
    if not size and upscale_queue_settings(item):
        size = f"{flag('--resolution')}p" if flag("--resolution") else f"{flag('--scale') or '2'}× upscale"
    if not size and flag("--aspect"):
        aspect, megapixels = flag("--aspect"), flag("--megapixels") or "1"
        size = f"{'Source aspect' if aspect == 'image' else aspect}" + (f" at {megapixels} MP" if megapixels != "image" else " · source size")
    if not size and item.get("pipeline", "shorts") == "shorts":
        size = (os.getenv("AVATAR_SIZE") or "736x1280").lower()
    upscale = item_upscale(item)
    return {"workflow": display_label(os.path.basename(workflow)) if workflow else "Built-in",
            "resolution": size or ("As the run was set up" if "--resume" in argv else "The workflow's own"),
            **({"count": int(count)} if count and count.isdigit() and int(count) > 0 else {}),
            **({"upscale": upscale} if upscale else {}),
            **({"prompt": item["prompt"]} if item.get("prompt") else {})}


def notify_ended(item, outcome, note=None):
    """
    Tells your phone a job ended, through ntfy (https://ntfy.sh), when NTFY_TOPIC is set in .env: install the ntfy app
    and subscribe to that topic. NTFY_SERVER for your own server. Sent in the background: a slow server holds nothing up.
    """
    topic = os.getenv("NTFY_TOPIC")
    if not topic or outcome not in ("done", "failed"):
        return
    title = f"{'Finished' if outcome == 'done' else 'Failed'}: {item.get('label') or 'a job'}"
    side = {"shorts": "Shorts", "video": "Video", "image": "Image"}.get(item.get("pipeline"), "Upload")
    message = f"{side}{f' · {note}' if note else ''}"
    url = f"{(os.getenv('NTFY_SERVER') or 'https://ntfy.sh').rstrip('/')}/{topic}"

    def send():
        try:
            requests.post(url, data=message.encode("utf-8"), timeout=10,
                          headers={"Title": title.encode("utf-8"), "Tags": "white_check_mark" if outcome == "done" else "x"})
        except requests.RequestException:
            pass  # A notification that doesn't arrive costs nothing else
    threading.Thread(target=send, daemon=True).start()


def form_options(form, takes):
    """
    The workflow's own options as the form sets them (core/workflow_options.py): only what differs from the workflow as
    saved. Returns (chosen, error). A checkbox sends a hidden "0" before its own "1", so the last value is the one that
    counts. A way for the workflow to write its own prompt is chosen with the LLM instead, so it isn't here.
    """
    from core import workflow_options
    options = takes.get("options") or []
    chosen = {}
    for option in options:
        name = f"opt_{option['id']}"
        if option.get("role"):
            continue
        if option["kind"] == "strength":
            if f"{name}_on" in form:
                on = form.getlist(f"{name}_on")[-1] == workflow_options.ON
                chosen[option["id"]] = (form.get(f"{name}_strength") or option.get("usual") or "1").strip() if on else workflow_options.OFF
        elif name in form:
            chosen[option["id"]] = form.getlist(name)[-1].strip()
    chosen = {key: value for key, value in chosen.items() if value != next(option["default"] for option in options if option["id"] == key).strip()}
    error = workflow_options.check(options, chosen)
    return (None, error) if error else (chosen, None)


def password_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not os.getenv("APP_PASSWORD") or session.get("authed"):
            return view(*args, **kwargs)
        return redirect(url_for("login", next=request.path))
    return wrapper


def _read_video_file_metadata(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=10, check=True,
        )
        data = json.loads(result.stdout)
        stream = (data.get("streams") or [{}])[0]
        width, height = stream.get("width"), stream.get("height")
        duration = data.get("format", {}).get("duration")
        return {"resolution": f"{width}x{height}" if width and height else None,
                "duration": float(duration) if duration is not None else None}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        app.logger.warning("Could not read video metadata for %s: %s", path, error)
        return {"resolution": None, "duration": None}


_video_metadata_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-metadata")


@lru_cache(maxsize=1024)
def _video_metadata_task(path, modified_ns, size):
    return _video_metadata_pool.submit(_read_video_file_metadata, path)


def video_file_metadata(path, modified_ns, size):
    task = _video_metadata_task(path, modified_ns, size)
    return task.result() if task.done() else {"resolution": None, "duration": None}


def list_videos(folder):
    directory = FOLDERS[folder]
    if not os.path.isdir(directory):
        return []

    captions = PIPELINES[FOLDER_PIPELINES[folder]].captions()
    videos = []
    for name in os.listdir(directory):
        if not name.endswith(".mp4"):
            continue
        stat = os.stat(os.path.join(directory, name))
        videos.append({
            "name": name,
            **captions(name),
            **video_file_metadata(os.path.join(directory, name), stat.st_mtime_ns, stat.st_size),
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "created": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m %H:%M"),
            "mtime": stat.st_mtime,
        })

    videos.sort(key=lambda v: v["mtime"], reverse=True)
    # A film's pills, against the others made from its prompt; the prompt itself stays here.
    pills.with_pills([video for video in videos if "_facts" in video])
    return videos


def safe_video_path(folder, name):
    """
    Resolves name inside one of the video folders, refusing anything that escapes it.
    """
    directory = FOLDERS.get(folder)
    if not directory:
        abort(404)
    path = os.path.abspath(os.path.join(directory, name))
    if os.path.dirname(path) != os.path.abspath(directory) or not os.path.exists(path):
        abort(404)
    return path


NSFW_PATH = os.path.join(LOGS_DIR, "nsfw.json")
_nsfw_lock = threading.Lock()


def _read_nsfw():
    try:
        with open(NSFW_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"image": [], "video": [], "video_file": [], "video_sources": {}}
    if not isinstance(data, dict) or any(not isinstance(data.get(key), list) or
                                         not all(isinstance(value, str) for value in data[key])
                                         for key in ("image", "video", "video_file")):
        raise ValueError("Invalid private tags file.")
    sources = data.setdefault("video_sources", {})
    if not isinstance(sources, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in sources.items()):
        raise ValueError("Invalid private video sources.")
    return data


# Private mode (Settings, saved): what is made is tagged NSFW, and Output opens on the NSFW filter.
def private_mode():
    try:
        return settings.load()["private_mode"]
    except (OSError, ValueError):
        return False


def tag_run_nsfw(pipeline, run_id):
    """Tags a run NSFW: an image set by its id, a film by the run that makes it. Returns whether it is tagged."""
    key = {"image": "image", "video": "video"}.get(pipeline)
    if not key or not run_id:
        return False
    try:
        with _nsfw_lock:
            tags = _read_nsfw()
            if run_id not in tags[key]:
                tags[key] = sorted({*tags[key], run_id})
                os.makedirs(os.path.dirname(NSFW_PATH), exist_ok=True)
                temp = NSFW_PATH + ".tmp"
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(tags, f, ensure_ascii=False, indent=2)
                os.replace(temp, NSFW_PATH)
        return True
    except (OSError, ValueError) as e:
        app.logger.error("Could not tag a run as private: %s", e)
        return False


@app.route("/api/private", methods=["GET", "POST"])
@password_required
def api_private():
    """Private mode, on or off: saved with the settings, so it stays on over a restart."""
    if request.method == "POST":
        try:
            settings.update({"private_mode": bool((request.get_json(silent=True) or {}).get("on"))})
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Could not save it: {e}"}, 500
    return {"ok": True, "on": private_mode()}


def _video_nsfw_key(name, films=None):
    run = run_of_film(name, films)
    return ("video", run) if run else ("video_file", name)


def _current_films(results, film_runs):
    """
    Finished opens a run's film by its name as it is now: one stitched again under another name (it had a name another
    run had) is found there. An upscaled copy is a file of its own, and keeps the name it was given.
    """
    finals = {state.id: name for name, state in film_runs.items() if state.final}
    for result in results:
        name = finals.get(result.get("run_id"))
        if result.get("pipeline") == "video" and name and result.get("film") and not UPSCALED.search(result["film"]):
            result["film"] = name


def _apply_nsfw(payload, tags, film_runs, private=False):
    image_tags, video_tags, video_files = (set(tags[key]) for key in ("image", "video", "video_file"))
    tagged_films = set()
    for film in payload["videos"]["video"]:
        kind, value = _video_nsfw_key(film["name"], film_runs)
        source = UPSCALED.sub(".mp4", film["name"])
        film["nsfw"] = (kind == "video" and value in video_tags) or source in video_files or tags["video_sources"].get(source) in video_tags
        if film["nsfw"]:
            tagged_films.add(film["name"])
    for image_set in payload["image_sets"]:
        image_set["nsfw"] = image_set["id"] in image_tags

    def tagged(result):
        if result.get("private"):
            return True
        if result.get("pipeline") == "image":
            return result.get("run_id") in image_tags
        if result.get("pipeline") == "video":
            return result.get("run_id") in video_tags or result.get("film") in tagged_films
        return False

    # Kept and marked: Finished shows what is NSFW only under the NSFW filter, which only the page knows.
    # What the job going now makes in Private mode is NSFW even before its run is tagged.
    payload["finished_results"] = [{**result, "nsfw": tagged(result)} for result in payload["queue"]["results"]]
    payload["made_now"] = [{**result, "nsfw": private or tagged(result)} for result in payload["made_now"]]
    # What waits, what runs and what is pending: out of Private mode the page shows a plain title for these instead.
    queue = payload["queue"]
    for item in [*queue.get("items", []), *([queue["current"]] if queue.get("current") else [])]:
        run_id = (payload.get("progress") or {}).get("run_id") if item is queue.get("current") else None
        item["nsfw"] = bool(item.get("private")) or tagged({"pipeline": item.get("pipeline"), "run_id": run_id or item.get("resume"),
                                                            "film": item.get("film")})
    for run in payload.get("stopped_runs", []):
        run["nsfw"] = tagged({"pipeline": run.get("pipeline"), "run_id": run.get("id")})


@app.route("/api/work/nsfw", methods=["POST"])
@password_required
def tag_work_nsfw():
    """Marks waiting, running or failed work private before it has output to tag."""
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or body.get("kind") not in ("job", "failed", "image", "video")
            or not isinstance(body.get("id"), str) or body.get("nsfw") is not True):
        return {"ok": False, "error": "Choose a run to mark private."}, 400
    kind, identifier = body["kind"], body["id"]
    with run_queue.lock:
        item = result = None
        if kind in ("job", "failed"):
            if not identifier.isascii() or not identifier.isdecimal():
                return {"ok": False, "error": "Choose a job by its number."}, 400
            job_id = int(identifier)
            if kind == "job":
                item = next((entry for entry in [run_queue.current, *run_queue.items]
                             if entry and entry["id"] == job_id), None)
            if item is None:
                # It may have finished between the tap and this request.
                result = next((entry for entry in run_queue.results if entry.get("job_id") == job_id), None)
                item = result and result.get("job")
            target = item if item is not None else result
            if target is None:
                return {"ok": False, "error": "That job is no longer in the list."}, 404
            side = target.get("pipeline")
            run_id = ((job.progress or {}).get("run_id") if item is not None and item is run_queue.current else None) \
                or target.get("resume") or (result or {}).get("run_id")
        else:
            side, run_id = kind, identifier
            if not PIPELINES[side].load_run(run_id):
                return {"ok": False, "error": "That run is no longer saved."}, 404
        if side not in ("image", "video"):
            return {"ok": False, "error": "Only image and video runs support private tags."}, 400
        if run_id and not tag_run_nsfw(side, run_id):
            return {"ok": False, "error": "Could not save the private tag. Check the panel log."}, 500
        if item is not None:
            item["private"] = True
            item.pop("private_tagged", None)
        if result is not None and not result.get("run_id"):
            result["private"] = True
        for entry in [run_queue.current, *run_queue.items]:
            if entry and run_id and entry.get("pipeline") == side and entry.get("resume") == run_id:
                entry["private"] = True
                entry.pop("private_tagged", None)
        queue_saved = run_queue._save()
        results_saved = run_queue._save_results()
        if not queue_saved or not results_saved:
            return {"ok": False, "error": "Marked private in memory, but could not save it. Retry before restarting the panel."}, 500
    return {"ok": True}


@app.route("/api/output/nsfw", methods=["POST"])
@password_required
def tag_nsfw():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("kind") not in ("image", "video") or not isinstance(body.get("id"), str) or not isinstance(body.get("nsfw"), bool):
        return {"ok": False, "error": "Invalid output tag."}, 400
    kind, identifier = body["kind"], body["id"]
    if kind == "image":
        if not PIPELINES["image"].load_run(identifier):
            return {"ok": False, "error": "That image batch no longer exists."}, 404
        key, value = "image", identifier
    else:
        safe_video_path("video", identifier)
        key, value = _video_nsfw_key(identifier)
    try:
        with _nsfw_lock:
            tags = _read_nsfw()
            if kind == "video":
                source = UPSCALED.sub(".mp4", identifier)
                if key == "video_file":
                    value = source
                    if not body["nsfw"] and source in tags["video_sources"]:
                        key, value = "video", tags["video_sources"][source]
                if key == "video":
                    if body["nsfw"]:
                        tags["video_sources"][source] = value
                    else:
                        tags["video_sources"] = {name: run for name, run in tags["video_sources"].items() if run != value}
                    tags["video_file"] = [name for name in tags["video_file"] if name != source]
            values = set(tags[key])
            if body["nsfw"]:
                values.add(value)
            else:
                values.discard(value)
            tags[key] = sorted(values)
            os.makedirs(os.path.dirname(NSFW_PATH), exist_ok=True)
            temp = NSFW_PATH + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(tags, f, ensure_ascii=False, indent=2)
            os.replace(temp, NSFW_PATH)
    except (OSError, ValueError) as e:
        app.logger.error("Could not save private tags: %s", e)
        return {"ok": False, "error": "Could not save private tags. Check the panel log."}, 500
    return {"ok": True}


def saved_at(path):
    """When a run was last saved, as the panel shows it. Empty if that can't be told."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d %b %H:%M")
    except OSError:
        return ""


def lan_ip():
    """The address other devices on the home network reach this PC at."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))  # No packet is sent; this only picks the outgoing interface.
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


_comfyui_cache = {"at": 0.0, "online": False}
_comfyui_start_lock = threading.Lock()
_comfyui_start_requested_at = 0.0
_comfyui_process = None  # Only one this server started
# Seconds a run waits for a ComfyUI that Generate just launched to load its models.
COMFYUI_STARTUP_WAIT = 180


def _check_comfyui():
    url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    try:
        online = requests.get(f"{url}/system_stats", timeout=2).status_code == 200
    except requests.RequestException:
        online = False
    # Not answering, yet its port is open: running, but too busy to reply, as when it pages for want of memory.
    _comfyui_cache.update(online=online, listening=online or _port_open(url), at=time.time())


_comfyui_checking = threading.Lock()


def _check_comfyui_in_background():
    try:
        _check_comfyui()
    finally:
        _comfyui_checking.release()


def comfyui_online(wait=True):
    """
    Whether ComfyUI answers, checked at most every 10 seconds. wait=False is for the page's status: it answers with
    what was last found and checks again in the background, so a ComfyUI too busy to reply can't hold the page up.
    """
    if time.time() - _comfyui_cache["at"] > 10:
        if wait or not _comfyui_cache["at"]:
            _check_comfyui()
        elif _comfyui_checking.acquire(blocking=False):
            threading.Thread(target=_check_comfyui_in_background, daemon=True).start()
    return _comfyui_cache["online"]


def _port_open(url):
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


def comfyui_listening():
    comfyui_online(wait=False)
    return _comfyui_cache.get("listening", False)


def ram_stats():
    """This PC's memory, in GB, or None without psutil: what ComfyUI runs short of first."""
    try:
        import psutil
        memory = psutil.virtual_memory()
    except Exception:
        return None
    return {"free": round(memory.available / 2 ** 30, 1), "total": round(memory.total / 2 ** 30, 1)}


# What each node of the workflows is doing, in plain words.
COMFY_LABELS = {
    "UNETLoader": "Loading the model", "UnetLoaderGGUF": "Loading the model", "CLIPLoader": "Loading the text encoder",
    "DualCLIPLoader": "Loading the text encoder", "DualCLIPLoaderGGUF": "Loading the text encoder",
    "VAELoader": "Loading the VAE", "VAELoaderKJ": "Loading the audio VAE",
    "LatentUpscaleModelLoader": "Loading the upscaler",
    "LoadImage": "Loading the reference image", "LoadAudio": "Loading the narration",
    "CLIPTextEncode": "Reading the prompt", "LTXVAudioVAEEncode": "Encoding the narration",
    "LTXVImgToVideoInplace": "Placing the reference image", "LTXVPreprocess": "Preparing the image",
    "SamplerCustomAdvanced": "Generating video", "LTXVLatentUpsampler": "Upscaling",
    "VAEDecodeTiled": "Decoding frames", "LTXVAudioVAEDecode": "Decoding audio",
    "VHS_VideoCombine": "Saving the video", "TextEncodeQwenImageEditPlus": "Reading the prompt", "KSampler": "Generating the image",
    "VAEEncode": "Encoding the image", "VAEDecode": "Decoding the image", "PreviewImage": "Saving the image",
    "VAEDecodeAudio": "Decoding audio", "MiniMaxH3SigmaShift": "Setting up the sampler", "ImageScale": "Sizing the image",
    # Herrgotts H3 Infinite Continuation Suite (pipelines/video/h3_infinite.py)
    "H3ContinuousStartV14": "Preparing the first clip", "H3ContinuousLoadLatent": "Loading the clip before",
    "H3ContinuousContinueV14": "Carrying on from the clip before",
    "H3ContinuousAnalyzeHandoverV14": "Finding where the next clip takes over",
    "H3ContinuousSaveLatent": "Saving the clip for the next one", "H3ContinuousStitchOutputV14": "Trimming the clip",
    "H3ContinuousStitchSavedChainV14": "Stitching the clips",
}


class ComfyMonitor:
    """
    Listens on ComfyUI's websocket (as the pipeline's client id, since ComfyUI
    only sends progress to the client that queued the job) and keeps the latest
    state: which node is running, sampling steps, queue size.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"connected": False, "queue": 0}
        self.nodes = {}
        self.samplers_seen = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _base(self):
        return (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")

    def _loop(self):
        client_id = comfyui_client_id()
        while True:
            url = self._base().replace("http", "ws", 1) + f"/ws?clientId={client_id}"
            try:
                ws = websocket.create_connection(url, timeout=10)
                ws.settimeout(None)
                with self.lock:
                    self.state["connected"] = True
                while True:
                    message = ws.recv()
                    if isinstance(message, str):  # Binary frames are sampler previews
                        self._handle(json.loads(message))
            except Exception:
                with self.lock:
                    self.state = {"connected": False, "queue": 0}
                time.sleep(5)

    def _load_nodes(self, prompt_id):
        """Node id -> class for the running prompt, from ComfyUI's queue."""
        try:
            queue = requests.get(f"{self._base()}/queue", timeout=5).json()
            for entry in queue.get("queue_running", []):
                if entry[1] == prompt_id:
                    return {k: v.get("class_type", "") for k, v in entry[2].items()}
        except Exception:
            pass
        return {}

    def _note(self, text, kind="🎛️ ComfyUI · "):
        """A line in the run's log, from ComfyUI's side: what it did, and how long it took."""
        if job.running:
            job.log(f"{kind}{text}")

    def _close(self):
        """Says what the node that just ended took, when it was worth saying: a second or more, or sampling steps."""
        s = self.state
        started, steps = getattr(self, "node_at", None), getattr(self, "node_steps", None)
        self.node_at = self.node_steps = None
        if started is None or not s.get("label") or s.get("node") is None:
            return
        seconds = time.time() - started
        if seconds >= 1 or steps:
            self._note(f"{s['label']}{f' · {steps} steps' if steps else ''} · {int(seconds)}s")

    def _handle(self, msg):
        kind, data = msg.get("type"), msg.get("data") or {}
        with self.lock:
            s = self.state
            if kind == "status":
                s["queue"] = data.get("status", {}).get("exec_info", {}).get("queue_remaining", 0)
            elif kind == "execution_start":
                self.nodes = self._load_nodes(data.get("prompt_id"))
                self.samplers_seen = []
                self.node_at = self.node_steps = None
                s.update(active=True, started=time.time(), node=None, label="Starting", value=None, max=None)
                self._note(f"started a workflow of {len(self.nodes)} nodes" if self.nodes else "started a workflow")
            elif kind == "executing":
                node = data.get("node")
                self._close()
                if node is None:
                    s.update(active=False, label="Idle", node=None, value=None, max=None)
                    return
                cls = self.nodes.get(str(node), "")
                label = COMFY_LABELS.get(cls, cls or f"Node {node}")
                if cls == "SamplerCustomAdvanced":
                    if node not in self.samplers_seen:
                        self.samplers_seen.append(node)
                    passes = sum(1 for c in self.nodes.values() if c == cls)
                    label += f" - pass {self.samplers_seen.index(node) + 1} of {passes}"
                s.update(active=True, node=node, label=label, value=None, max=None)
                self.node_at = time.time()
            elif kind == "progress":
                s.update(value=data.get("value"), max=data.get("max"))
                self.node_steps = data.get("max")
            elif kind in ("execution_success", "execution_error", "execution_interrupted"):
                self._close()
                if kind == "execution_error":
                    where = data.get("node_type") or "a node"
                    self._note(f"failed in {where}: {str(data.get('exception_message') or 'no reason given').strip()[:300]}", "❌ ComfyUI ")
                elif kind == "execution_interrupted":
                    self._note("stopped", "⚠️ ComfyUI ")
                else:
                    total = int(time.time() - s["started"]) if s.get("started") else None
                    self._note(f"finished{f' in {total}s' if total is not None else ''}")
                s.update(active=False, label="Idle" if kind == "execution_success" else kind.replace("_", " "),
                         node=None, value=None, max=None)

    def snapshot(self):
        with self.lock:
            s = dict(self.state)
        if s.get("started") and s.get("active"):
            s["elapsed"] = int(time.time() - s["started"])
        s.pop("started", None)
        return s


comfy_monitor = None
_gpu_cache = {"at": 0.0, "value": None}


_gpu_checking = threading.Lock()


def gpu_stats():
    """
    Utilisation / VRAM / power from nvidia-smi, cached for a few seconds. Once it has a reading, a new one is taken in
    the background: under load nvidia-smi can take seconds, and the page's status shouldn't wait for it.
    """
    if time.time() - _gpu_cache["at"] < 3:
        return _gpu_cache["value"]
    if _gpu_cache["value"] is None:
        return _read_gpu()
    if _gpu_checking.acquire(blocking=False):
        def read():
            try:
                _read_gpu()
            finally:
                _gpu_checking.release()
        threading.Thread(target=read, daemon=True).start()
    return _gpu_cache["value"]


def _read_gpu():
    _gpu_cache["at"] = time.time()
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
            creationflags=NO_WINDOW,
        ).stdout.strip().splitlines()[0]
        util, used, total, power, temp = [x.strip() for x in out.split(",")]
        _gpu_cache["value"] = {"util": int(float(util)), "mem_used": round(float(used) / 1024, 1),
                               "mem_total": round(float(total) / 1024, 1),
                               "power": int(float(power)), "temp": int(float(temp))}
    except Exception:
        _gpu_cache["value"] = None
    return _gpu_cache["value"]


def comfyui_launcher():
    path = os.getenv("COMFYUI_LAUNCHER")
    return path if path and os.path.exists(path) else None


def cancel_pipeline_clips():
    """
    Cancels the avatar clips ComfyUI has for a stopped run, rendering or waiting.
    Only the pipeline's, by client id: a render you started in ComfyUI yourself
    carries on. ComfyUI itself keeps running, with its models loaded for the next run.
    """
    url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    client_id = comfyui_client_id()
    try:
        queue = requests.get(f"{url}/queue", timeout=5).json()
        waiting = [entry[1] for entry in queue.get("queue_pending", []) if entry[3].get("client_id") == client_id]
        # Waiting ones first, or the next clip starts as soon as this one stops.
        if waiting:
            requests.post(f"{url}/queue", json={"delete": waiting}, timeout=5)
        for entry in queue.get("queue_running", []):
            if entry[3].get("client_id") == client_id:
                requests.post(f"{url}/interrupt", json={"prompt_id": entry[1]}, timeout=5)
    except requests.ConnectionError:
        pass  # ComfyUI isn't running, so it has nothing to cancel
    except (requests.RequestException, ValueError, LookupError, AttributeError) as e:
        job.log(f"⚠️ Could not cancel the ComfyUI clip, it may keep rendering: {e}")


def _comfyui_workflow(item):
    """The ComfyUI workflow a queued job runs, or None if it uses none: Shorts with stock footage only."""
    env = (item or {}).get("env") or {}
    if env.get("COMFYUI_WORKFLOW"):
        return env["COMFYUI_WORKFLOW"]
    if (item or {}).get("pipeline", "shorts") == "shorts" and env.get("AVATAR_SOURCE") != "comfyui":
        return None
    # No workflow file: told apart by what runs it. An RTX upscale, an image upscale and Shorts' avatars each load
    # their own models, and one ending must free them before another starts.
    argv = (item or {}).get("argv") or []
    module = argv[argv.index("-m") + 1] if "-m" in argv[:-1] else (item or {}).get("pipeline")
    return f"built-in:{module}"


def frees_comfyui(item, ahead):
    """
    Whether ComfyUI should let go of its models once this job ends: when it used ComfyUI, unless the job that starts
    next runs the same workflow, which would only load them again.
    """
    used = _comfyui_workflow(item)
    return bool(used) and used != _comfyui_workflow(ahead)


def free_comfyui():
    """
    Has ComfyUI unload every model and clear its node cache, as its own Free model and node cache does. It keeps
    what it loaded otherwise: after a morning of MiniMax H3 and Krea 2 runs it held over 57 GB on a 32 GB PC, and
    paged so hard it stopped answering mid-render. Idle, it does this at once; it cancels nothing.
    """
    url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    from core import comfy_memory
    global _comfy_freeing
    try:
        job.log("🧹 Waiting for ComfyUI to finish clearing its models and caches...")
        comfy_memory.release(url)
        job.log("🧹 ComfyUI cleanup confirmed: models and caches released.")
    except RuntimeError as error:
        job.log(f"⚠️ ComfyUI cleanup failed; the generation queue is on hold: {error}")
        with run_queue.lock:
            run_queue.held = True
            run_queue._save()
    finally:
        with run_queue.lock:
            _comfy_freeing = False


def remove_partial_videos():
    """A stitch that gets killed leaves its unfinished file behind in the output folder."""
    try:
        for folder in (SHORTS_READY, VIDEO_OUTPUT):
            for name in os.listdir(folder) if os.path.isdir(folder) else ():
                if name.endswith(".part"):
                    os.remove(os.path.join(folder, name))
        # Each set of images has a folder of its own.
        for folder, _, names in os.walk(IMAGE_OUTPUT):
            for name in names:
                if name.endswith(".part"):
                    os.remove(os.path.join(folder, name))
    except OSError as e:
        job.log(f"⚠️ Could not remove the unfinished video: {e}")


def close_comfyui():
    """Closes ComfyUI if this server started it. One you started yourself isn't the panel's to close."""
    if _comfyui_process and _comfyui_process.poll() is None:
        kill_tree(_comfyui_process.pid)


def comfyui_command(launcher):
    """
    The ComfyUI command line from a start script such as the portable build's
    run_nvidia_gpu.bat, with --disable-auto-launch added so no browser tab
    opens: the panel only needs its API. None if the script has no main.py line.
    """
    try:
        with open(launcher, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if "main.py" in line and not line.lower().startswith(("rem", "::", "echo")):
                    if "--disable-auto-launch" not in line:
                        line += " --disable-auto-launch"
                    reserve = settings.load()["reserve_ram_gb"]
                    if reserve and "--cache-ram" not in line:
                        line += f" --cache-ram {reserve:g}"
                    return line
    except OSError:
        pass
    return None


def launch_comfyui(launcher):
    """
    Starts ComfyUI without a visible console window. It outlives a server
    restarting for new code; Shut down closes it.
    """
    global _comfyui_process
    command = comfyui_command(launcher)
    if os.name != "nt":
        _comfyui_process = subprocess.Popen(command or [launcher], shell=bool(command),
                                            cwd=os.path.dirname(launcher), start_new_session=True)
        return
    _comfyui_process = subprocess.Popen(
        f"cmd /c {command}" if command else ["cmd", "/c", launcher],
        cwd=os.path.dirname(launcher),
        creationflags=NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | priority_flags(),
    )


def comfyui_processes():
    """The ComfyUI processes running on this PC, started by this server or not."""
    try:
        import psutil
    except ImportError as e:
        raise RuntimeError("Process inspection requires psutil; install the panel's requirements.") from e
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        if process.pid == os.getpid() or not (process.info.get("name") or "").lower().startswith("python"):
            continue
        args = process.info.get("cmdline")
        if args is None:
            raise RuntimeError(f"Cannot inspect Python process {process.pid}; ComfyUI may still be running.")
        for arg in args[1:]:
            path = arg.replace("\\", "/").lower()
            if path.endswith("/main.py") and "comfyui" in path:
                found.append(process)
                break
            if path == "main.py":
                try:
                    if "comfyui" in process.cwd().lower():
                        found.append(process)
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied as e:
                    raise RuntimeError(f"Cannot inspect Python process {process.pid}; ComfyUI may still be running.") from e
                break
            if path.endswith(".py") or path in ("-m", "-c"):
                break
    return found


def start_fresh_comfyui():
    """Stops local ComfyUI processes before a manual start, without touching unrelated Python processes."""
    try:
        import psutil
    except ImportError as e:
        raise RuntimeError("Process inspection requires psutil; install the panel's requirements.") from e
    global _comfyui_start_requested_at
    with _comfyui_start_lock:
        launcher = comfyui_launcher()
        if not launcher:
            raise RuntimeError("COMFYUI_LAUNCHER isn't set in .env, so the panel can't start ComfyUI.")
        try:
            processes = comfyui_processes()
            for process in processes:
                kill_tree(process.pid)
            _, alive = psutil.wait_procs(processes, timeout=10)
        except (psutil.Error, OSError) as e:
            raise RuntimeError(f"Could not inspect or stop local ComfyUI processes: {e}") from e
        if alive:
            raise RuntimeError(f"Could not stop ComfyUI process(es): {', '.join(str(p.pid) for p in alive)}.")
        url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
        if _port_open(url):
            raise RuntimeError("The ComfyUI address is still in use after stopping local processes; no new instance was started.")
        _comfyui_start_requested_at = 0.0
        _comfyui_cache["at"] = 0.0
        try:
            launch_comfyui(launcher)
        except OSError as e:
            raise RuntimeError(f"Could not start ComfyUI: {e}") from e
        _comfyui_start_requested_at = time.time()
        _comfyui_cache["at"] = 0.0


def apply_comfyui_priority():
    """Sets ComfyUI running now to the priority the setting asks for. One it starts itself starts at it."""
    try:
        import psutil
        low = settings.load()["low_priority"]
        for process in comfyui_processes():
            try:
                if os.name == "nt":
                    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if low else psutil.NORMAL_PRIORITY_CLASS)
                else:
                    process.nice(10 if low else 0)
            except psutil.Error:
                pass  # Gone already, or not ours to change
    except Exception as e:
        job.log(f"⚠️ Could not change ComfyUI's priority: {e}")


def start_comfyui():
    """Starts ComfyUI if a launcher is configured. Returns True when it is (still) booting."""
    global _comfyui_start_requested_at
    with _comfyui_start_lock:
        _comfyui_cache["at"] = 0.0
        if comfyui_online():
            return False
        launcher = comfyui_launcher()
        if not launcher:
            return False
        if time.time() - _comfyui_start_requested_at < COMFYUI_STARTUP_WAIT:
            return True  # Launched moments ago and still loading.
        try:
            launch_comfyui(launcher)
        except OSError as e:
            raise RuntimeError(f"Could not start ComfyUI: {e}") from e
        _comfyui_start_requested_at = time.time()
        _comfyui_cache["at"] = 0.0
        return True


_quota_cache = {"at": 0.0, "value": None}


def cached_quota():
    # Cached briefly: every open browser polls status every 2s.
    if time.time() - _quota_cache["at"] > 5:
        _quota_cache["value"] = quota_summary()
        _quota_cache["at"] = time.time()
    return _quota_cache["value"]


def item_images(item):
    return ([item["image"]] if item.get("image") else []) + item.get("references", [])


def prepare_run(item):
    """ComfyUI starts when the run does, not when it is queued: it may not be needed for hours."""
    pipeline = item.get("pipeline", "shorts")
    if item.get("resume") and not PIPELINES[pipeline].load_run(item["resume"]):
        return "its saved run is gone"
    if not all(os.path.exists(path) for path in item_images(item)):
        return "its image is gone"
    if item.get("plan_only"):
        return None  # Writing the prompts needs no GPU
    try:
        always = pipeline in ("video", "image")
        needs_comfyui = always or (item["form"].get("avatar_source") or "comfyui") == "comfyui"
        if needs_comfyui and (always or (item["form"].get("avatar_clips") or "auto") != "0") and start_comfyui():
            item["env"] = {**(item.get("env") or {}), "COMFYUI_STARTUP_WAIT": str(COMFYUI_STARTUP_WAIT)}
    except RuntimeError as e:
        return str(e)
    return None


def prepare_upload(item):
    """Drops videos deleted or uploaded while this upload waited its turn."""
    gone = [name for name in item["videos"] if not os.path.exists(os.path.join(FOLDERS["output"], name))]
    if len(gone) == len(item["videos"]):
        return "no longer in Ready"
    item["argv"] = [arg for arg in item["argv"] if arg not in gone]
    item["videos"] = [name for name in item["videos"] if name not in gone]
    return None


_writing_prompt = False
_prompt_refiner = None
_panel_closing = False
_comfy_restarting = False
_comfy_freeing = False

# --- The prompt writer's warm model ---
# Writing a prompt again soon after (a retry, the other form's prompt) would otherwise load the model again: 7-11 s
# each time. So the model the writer used stays loaded for WARM_SECONDS after it answers. Whatever else needs the GPU
# closes it first: a job starting (the queue waits for it), the workflow's own prompt enhancer, and the panel exiting.
WARM_SECONDS = 90
_warm_lock = threading.Lock()
_warm = None  # (refiner, timer) while a model is kept loaded
_warm_closing = False


def keep_warm(refiner):
    global _warm
    timer = threading.Timer(WARM_SECONDS, close_warm_writer, kwargs={"only": refiner})
    timer.daemon = True
    with _warm_lock:
        old, _warm = _warm, (refiner, timer)
    if old:
        _close_warm(old)
    timer.start()


def take_warm(model):
    """The warm model, now the caller's, when it is this one and still running; otherwise None, any other closed."""
    global _warm
    with _warm_lock:
        held, _warm = _warm, None
    if not held:
        return None
    refiner, timer = held
    timer.cancel()
    if refiner.model_id == model and refiner.process and refiner.process.poll() is None:
        return refiner
    _close_warm(held)
    return None


def warm_model():
    """Which model is kept loaded, or None."""
    with _warm_lock:
        return _warm[0].model_id if _warm else None


def close_warm_writer(only=None):
    """Closes the warm model (only that one, when given: its own timer must not close a newer one)."""
    global _warm
    with _warm_lock:
        if _warm is None or (only is not None and _warm[0] is not only):
            return
        held, _warm = _warm, None
    _close_warm(held)


def _close_warm(held):
    refiner, timer = held
    timer.cancel()
    try:
        refiner.__exit__(None, None, None)
    except Exception as error:  # Closing must not take what asked for it down with it
        app.logger.warning("Could not close the prompt writer's warm model: %s", error)


def warm_writer_in_the_way():
    """
    For the run queue: whether a warm model stands between it and its next job. It is then closed on a thread, as
    closing takes seconds and the queue's lock is held here, and the queue moves on once it's gone.
    """
    global _warm_closing
    with _warm_lock:
        if _warm is None:
            return _warm_closing
        if _warm_closing:
            return True
        _warm_closing = True

    def close():
        global _warm_closing
        try:
            close_warm_writer()
        finally:
            with _warm_lock:
                _warm_closing = False
            run_queue._advance_locked()
    threading.Thread(target=close, daemon=True).start()
    return True


def exit_soon():
    """Exits the panel in half a second, its answer sent first, and the warm model closed: os._exit skips atexit."""
    def leave():
        close_warm_writer()
        os._exit(0)
    threading.Timer(0.5, leave).start()


atexit.register(close_warm_writer)
# A ComfyUI restart going (after an aimdo error) holds the next run back until it is done.
run_queue = JobQueue(job, prepare_run, blocked=lambda: _writing_prompt or _panel_closing or _comfy_restarting or _comfy_freeing
                     or warm_writer_in_the_way(), path=os.path.join(LOGS_DIR, "queue_runs.json"))
# A run's own upload step is waited out, when its video sits in Ready with no topic recorded yet.
upload_queue = JobQueue(uploads, prepare_upload, blocked=lambda: job.uploading,
                        path=os.path.join(LOGS_DIR, "queue_uploads.json"))
QUEUES = {"run": run_queue, "upload": upload_queue}


def work_left():
    return _writing_prompt or job.running or uploads.running or run_queue.pending() or upload_queue.pending()


def restart_blocked():
    """
    Something a restart would cut short: a run or upload going, or a queue about to start one. A queue on hold
    isn't: it's saved, and comes back on hold.
    """
    return _writing_prompt or _comfy_freeing or job.running or uploads.running or any(
        not queue.held and any(not item.get("later") for item in queue.pending())
        for queue in (run_queue, upload_queue)
    )


_runs_cache = {"at": 0.0, "value": []}


def busy_runs():
    """The saved runs a job has in hand: the one going, and those queued to continue."""
    busy = {item.get("resume") for item in run_queue.pending()}
    if job.running:
        busy.add(job.progress.get("run_id"))
    return busy


def active_runs():
    """Runs going or in the active queue; pending continuations reserve their run but are not active."""
    busy = {item.get("resume") for item in run_queue.pending() if not item.get("later")}
    if job.running:
        busy.add(job.progress.get("run_id"))
    return busy


def saved_runs():
    # Cached briefly: every open browser polls status every 2s.
    if time.time() - _runs_cache["at"] > 3:
        _runs_cache["at"] = time.time()
        try:
            runs = [run for pipeline in PIPELINES.values() for run in pipeline.describe_runs()]
            # An image set's pills, against the others made from its prompt.
            pills.with_pills([run for run in runs if "_facts" in run])
            _runs_cache["value"] = runs
        except Exception as e:  # This is polled for the whole page: one odd run must not freeze it
            job.log(f"⚠️ Could not list the saved runs: {e}")
    return _runs_cache["value"]


# --- Why a run made nothing: kept in its folder, for Output to show beside what it did make ---

OUTCOME_FILE = "outcome.json"
STOPPED = {"outcome": "stopped"}  # Cancelled or stopped: it waits in Pending, marked, with nothing to explain
FIRST_ONLY = {"outcome": "first one made",
              "why": "A preview run: it stopped after the first. Open Prompts to see it and change the rest, "
                     "or continue to make them."}
NOT_RENDERED = {"outcome": "not rendered",
                "why": "You asked to read the prompts first (Let me read the prompts before rendering), so it stopped once "
                       "they were written. Open Prompts to change them, then render it."}
def restart_comfyui_in_background(force=False):
    """
    Force-restarts ComfyUI on a thread. The run queue waits while it does. Returns False when it can't: already
    restarting (unless force: a restart that hung is started over), or no launcher to start it again.
    """
    global _comfy_restarting
    if (_comfy_restarting and not force) or not comfyui_launcher():
        return False
    _comfy_restarting = True

    def restart():
        global _comfy_restarting
        try:
            restart_comfyui_now()
        finally:
            _comfy_restarting = False
    threading.Thread(target=restart, daemon=True).start()
    return True


def note_outcome(job, item, outcome):
    """Keeps why a run made nothing in its folder; None clears it, once it has made what it was asked for."""
    pipeline = item.get("pipeline")
    run_id = (job.progress or {}).get("run_id") or item.get("resume")
    if pipeline not in PIPELINES or not run_id:
        return
    try:
        state = PIPELINES[pipeline].load_run(run_id)
        if not state:
            return
        # Tried first, but there was only the one: it's done, there's nothing to say.
        if outcome is FIRST_ONLY and (getattr(state, "final", None) or (getattr(state, "finished", False) is True)):
            outcome = None
        path = os.path.join(state.folder, OUTCOME_FILE)
        if outcome:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({**outcome, "at": time.time()}, f, ensure_ascii=False)
        elif os.path.exists(path):
            os.remove(path)
    except (OSError, ValueError, AttributeError) as e:
        job.log(f"⚠️ Could not note how {item.get('label')} ended: {e}")
    _runs_cache["at"] = 0.0


def read_outcome(folder):
    """What note_outcome() kept for a run, or None."""
    try:
        with open(os.path.join(folder, OUTCOME_FILE), "r", encoding="utf-8") as f:
            found = json.load(f)
        return found if isinstance(found, dict) and found.get("outcome") else None
    except (OSError, ValueError):
        return None


def made_in_this_run():
    """
    What the job going now has already made: each finished image of a set, under Finished as it comes, rather than
    only once the whole set is done.
    """
    run_id = (job.progress or {}).get("run_id")
    if not job.running or job.pipeline != "image" or not run_id:
        return []
    try:
        state = PIPELINES["image"].load_run(run_id)
        started = job.started_at.timestamp() if job.started_at else 0
        made = []
        for position, shot in enumerate(state.shots if state else [], 1):
            if not shot.get("file"):
                continue
            made_at = os.path.getmtime(state.image_path(shot))
            # Only what this job made: a redo, or a set continued, kept the rest from before.
            if made_at < started:
                continue
            made.append({"label": f"{state.title or state.brief} · {shot.get('title') or shot['number']}", "outcome": "done",
                         "pipeline": "image", "run_id": state.id, "position": position,
                         "at": datetime.fromtimestamp(made_at).strftime("%H:%M"), "t": made_at})
        return made
    except (OSError, ValueError, AttributeError, KeyError):
        return []  # Being written as we look: the next poll has it


def stopped_runs():
    """What can be continued, with why it stopped if it didn't finish on its own. A finished film is reached from its video instead."""
    busy = busy_runs()
    return [run for run in saved_runs() if run["id"] not in busy and not run.get("finished")]


def run_pipeline(run_id):
    """Shorts' runs are numbered within their batch: run_20261101_120000_1. Image's start image_."""
    if run_id.startswith("image_"):
        return PIPELINES["image"]
    return PIPELINES["shorts" if re.fullmatch(r"run_\d{8}_\d{6}_\d+", run_id) else "video"]


def checkpoint_target(error):
    """Resolve a reported checkpoint to its configured run folder, never a client-supplied path."""
    from pipelines.image import paths as image_paths, run_state as image_state
    from pipelines.shorts import run_state as shorts_state
    from pipelines.video import paths as video_paths, run_state as video_state

    path = os.path.abspath(error["path"])
    folder, filename = os.path.split(path)
    root, run_id = os.path.split(folder)
    if filename != "state.json":
        return None
    for side, expected_root, pattern in (
        ("image", image_paths.RUNS_DIR, image_state.RUN_ID),
        ("video", video_paths.RUNS_DIR, video_state.RUN_ID),
        ("shorts", shorts_state.RUNS_DIR, shorts_state.RUN_ID),
    ):
        if os.path.normcase(root) == os.path.normcase(os.path.abspath(expected_root)) and pattern.fullmatch(run_id):
            return side, run_id, folder
    return None


def stop_run(start_next=False):
    """Kills the run with its ffmpeg renders and ComfyUI clips. What is queued waits for Resume, unless start_next."""
    # Before the kill, or the next job could start as soon as this one dies.
    if job.running:
        run_queue.hold()
    stopped = job.stop()
    if stopped:
        cancel_pipeline_clips()
        remove_partial_videos()
        _runs_cache["at"] = 0.0
        # Only now: the clean-up above would take the next job's clips and files with it.
        if start_next:
            run_queue.resume()
    return stopped


@app.errorhandler(413)
def too_large(error):
    return {"ok": False, "error": f"That file is over {MAX_UPLOAD_BYTES // 2 ** 20} MB."}, 413


@app.route("/login", methods=["GET", "POST"])
def login():
    expected = os.getenv("APP_PASSWORD")
    if not expected:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        # Constant-time compare so the password cannot be guessed by timing.
        if secrets.compare_digest(request.form.get("password", ""), expected):
            session["authed"] = True
            session.permanent = True
            target = request.args.get("next") or ""
            # Only back into this site: a link can't send you elsewhere after signing in.
            return redirect(target if re.fullmatch(r"/(?![/\\]).*", target) else url_for("index"))
        error = "Wrong password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


_saved_workflows_cache = {"at": 0.0, "online": None, "value": []}
_saved_workflows_lock = threading.Lock()


def saved_workflows():
    # Cached briefly: it asks ComfyUI about every node it has. Not across ComfyUI starting, which is when they appear.
    online = comfyui_online()
    with _saved_workflows_lock:
        cache = _saved_workflows_cache
        if time.time() - cache["at"] > 30 or cache["online"] != online:
            url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
            cache.update(at=time.time(), online=online, value=list_saved(url, SAVED_WORKFLOWS_DIR))
        return cache["value"]


def on_this_pc():
    return request.remote_addr in ("127.0.0.1", "::1")


def can_open_folders():
    """Explorer opens on the PC running the server, which is no use to someone on their phone."""
    return os.name == "nt" and on_this_pc()


# Status's idle nudges ("Why not try something neon today?"), written by Gemini once (scripts/make_nudges.py).
NUDGES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nudges.json")


def nudges():
    """The nudges, or none when the file is missing or broken: Status then simply says nothing."""
    try:
        with open(NUDGES_PATH, encoding="utf-8") as f:
            lines = json.load(f)
    except (OSError, ValueError):
        return []
    return [line for line in lines if isinstance(line, str) and line.strip()] if isinstance(lines, list) else []


@app.route("/")
@app.route("/shorts", endpoint="shorts_page")
@app.route("/video", endpoint="video_page")
@app.route("/image", endpoint="image_page")
@password_required
def index():
    port = request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"
    context = {}
    for pipeline in PIPELINES.values():
        context.update(pipeline.context())
    protected = bool(os.getenv("APP_PASSWORD"))
    tailscale_url, tailscale_problem = tailscale.reach(port) if protected else (None, None)
    return render_template(
        "index.html",
        protected=protected,
        phone_url=f"http://{lan_ip()}:{port}",
        tailscale_url=tailscale_url,
        tailscale_problem=tailscale_problem,
        settings=settings.load(),
        local_models=settings.local_models(),
        lora_ranges=lora_hints.RANGES,
        themes=settings.THEMES,
        can_open_folders=can_open_folders(),
        nudges=nudges(),
        # What a set's images or a film's clips may vary or keep: the chips under Variety.
        variety_chips=variety.chip_labels(), variety_chip_groups=variety.chip_groups(), variety_hints=variety.chip_hints(), variety_levels=variety.LEVELS,
        # Private mode's Explicit content: what the writer is told, shown under the box word for word.
        explicit_rule=explicit.RULE,
        # The page you asked for by address, or else the one it last showed.
        initial_pipeline=request.path.strip("/"),
        **context,
    )


@app.route("/runs/<run_id>/continue", methods=["POST"])
@password_required
def continue_run(run_id):
    """Starts a stopped run again from where it got to, or queues that behind the run in progress."""
    return run_pipeline(run_id).continue_run(run_id)


@app.route("/runs/<run_id>/discard", methods=["POST"])
@password_required
def discard_run(run_id):
    return run_pipeline(run_id).discard_run(run_id)


@app.route("/runs/<run_id>/discard-unreadable", methods=["POST"])
@password_required
def discard_unreadable_run(run_id):
    """Delete only an identified, still-unreadable and idle run folder."""
    with run_queue.lock:
        target = next((target for error in catalogue_errors()
                       if (target := checkpoint_target(error)) and target[1] == run_id), None)
        if not target:
            return {"ok": False, "error": "That unreadable run is no longer listed. Refresh and try again."}, 404
        side, _, folder = target
        if run_id in busy_runs():
            return {"ok": False, "error": "That run is going or queued. Stop it or remove it from the queue first."}, 409
        try:
            info = os.lstat(folder)
            if (os.path.islink(folder) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or os.path.normcase(os.path.dirname(os.path.realpath(folder))) != os.path.normcase(os.path.realpath(os.path.dirname(folder)))):
                return {"ok": False, "error": "The run folder is a link or has moved; delete it manually after checking its location."}, 409
            try:
                PIPELINES[side].load_run(run_id)
            except CheckpointError:
                pass
            else:
                return {"ok": False, "error": "The checkpoint is no longer unreadable. Refresh before deleting."}, 409
            shutil.rmtree(folder)
        except OSError as error:
            app.logger.error("Could not delete unreadable run %s: %s", folder, error)
            return {"ok": False, "error": f"Could not delete the run folder: {error}"}, 500
        _runs_cache["at"] = 0.0
    return {"ok": True}


@app.route("/stop", methods=["POST"])
@password_required
def stop():
    _cancelling["started_at"] = None  # Stop is all of it: a Cancel waiting to happen goes with it
    return {"ok": stop_run(), "error": STOP_FAILED if job.running else None}


# Held by Stop after this one, so taking it back lets the queue go on again; held before stays held.
_held_for_stop_after = False


@app.route("/stop-after", methods=["POST"])
@password_required
def stop_after():
    """
    Stop after this one: a batch ends once the video or image it's making now is done, and what is queued after it
    waits for Resume, as with Stop. Asked again, it takes that back. A film is one video, so it has nothing to stop.
    """
    global _held_for_stop_after
    if not job.running:
        return {"ok": False, "error": "Nothing is running."}, 409
    if job.pipeline == "video":
        return {"ok": False, "error": "A film is one video, so there is no batch to stop after it: use Stop or Skip."}, 409
    if batch_stop.requested():
        batch_stop.clear()
        job.log("▶️ The batch goes on: Stop after this one taken back.")
        if _held_for_stop_after:
            run_queue.resume()
        _held_for_stop_after = False
        return {"ok": True, "stop_after": False}
    _held_for_stop_after = not run_queue.held and bool(run_queue.items)
    batch_stop.request()
    run_queue.hold()
    job.log("⏸️ The batch stops once the one being made now is done.")
    return {"ok": True, "stop_after": True}


# Cancel asked for before the run had anything saved: it stops once it has (its plan or prompts written), for the job
# that was running then. {"started_at": ...} while waiting, else None.
_cancelling = {"started_at": None}


def run_saved():
    """Whether the running job's run is saved, so it can be stopped and continued later. Upscales and Shorts can always."""
    run_id = (job.progress or {}).get("run_id")
    current = run_queue.current or {}
    if current.get("pipeline") not in PIPELINES or current.get("pipeline") == "shorts" or is_upscale(current.get("argv")):
        return True
    return bool(run_id and PIPELINES[current["pipeline"]].load_run(run_id))


def cancel_now():
    """Stops the running job; the next in the queue starts if the queue is going, and a held queue stays held."""
    _cancelling["started_at"] = None
    return stop_run(start_next=not run_queue.held)


def _cancel_when_saved(started_at):
    while job.running and job.started_at == started_at and _cancelling["started_at"] == started_at:
        if run_saved():
            job.log("⏭️ Its plan is saved: cancelling it now.")
            cancel_now()
            return
        time.sleep(0.5)
    if _cancelling["started_at"] == started_at:
        _cancelling["started_at"] = None  # It ended on its own first


@app.route("/skip", methods=["POST"])
@password_required
def skip():
    """
    Cancels the running job: it stops, and waits under Stopped runs until you continue it, and the next in the queue
    starts if the queue is going. One with nothing saved yet to continue from stops as soon as it has.
    """
    _runs_cache["at"] = 0.0
    if not job.running:
        return {"ok": True, "cancelling": False}
    if run_saved():
        stopped = cancel_now()
        return {"ok": stopped, "error": STOP_FAILED if job.running and not stopped else None}
    started_at = job.started_at
    if _cancelling["started_at"] != started_at:
        _cancelling["started_at"] = started_at
        job.log("⏭️ Cancelling once its plan is saved: then the next in the queue starts.")
        threading.Thread(target=_cancel_when_saved, args=(started_at,), daemon=True).start()
    return {"ok": True, "cancelling": True}


@app.route("/publish/stop", methods=["POST"])
@password_required
def stop_upload():
    if uploads.running:
        upload_queue.hold()
    return {"ok": uploads.stop(), "error": STOP_FAILED if uploads.running else None}


@app.route("/queue/<lane>/remove/<int:item_id>", methods=["POST"])
@password_required
def queue_remove(lane, item_id):
    if lane not in QUEUES:
        abort(404)
    return {"ok": QUEUES[lane].remove(item_id)}


@app.route("/queue/finished/clear", methods=["POST"])
@password_required
def clear_finished():
    """Clears only the jobs the page showed; hidden or newly finished jobs stay."""
    selected = request.get_json(silent=True)
    if not isinstance(selected, dict) or set(selected) != set(QUEUES):
        return {"ok": False, "error": "Say which run and upload results to clear."}, 400
    if any(not isinstance(ids, list) or any(type(job_id) is not int for job_id in ids)
           for ids in selected.values()):
        return {"ok": False, "error": "Finished results are lists of job ids."}, 400
    for lane, queue in QUEUES.items():
        queue.clear_results(set(selected[lane]))
    return {"ok": True}


@app.route("/queue/<lane>/finished/<int:job_id>/forget", methods=["POST"])
@password_required
def queue_forget_result(lane, job_id):
    if lane not in QUEUES:
        abort(404)
    return {"ok": QUEUES[lane].forget_result(job_id)}


@app.route("/queue/<lane>/failed/<int:job_id>/dismiss", methods=["POST"])
@password_required
def queue_dismiss_failure(lane, job_id):
    if lane not in QUEUES:
        abort(404)
    return {"ok": QUEUES[lane].dismiss_failure(job_id)}


@app.route("/queue/<lane>/failed/<int:job_id>/requeue", methods=["POST"])
@password_required
def queue_requeue_failure(lane, job_id):
    """A failed job with no saved run, back in Pending with its settings."""
    if lane != "run":
        abort(404)
    item_id = run_queue.requeue_failure(job_id)
    if item_id is None:
        return {"ok": False, "error": "That failure is gone, or its settings were not kept."}, 404
    return {"ok": True, "id": item_id}


@app.route("/queue/<lane>/start/<int:item_id>", methods=["POST"])
@password_required
def queue_start(lane, item_id):
    if lane not in QUEUES:
        abort(404)
    return {"ok": QUEUES[lane].start(item_id, top=bool(request.args.get("top")))}


@app.route("/queue/<lane>/pause/<int:item_id>", methods=["POST"])
@password_required
def queue_pause(lane, item_id):
    if lane not in QUEUES:
        abort(404)
    return {"ok": QUEUES[lane].pause(item_id)}


def legacy_queue_form(item):
    """Reconstruct forms for generation jobs saved before form snapshots were kept."""
    argv, env = item.get("argv") or [], item.get("env") or {}
    pipeline = item.get("pipeline")
    if pipeline not in ("video", "image") or "--resume" in argv or not any(
        name in argv for name in ("pipelines.video.main", "pipelines.image.main")
    ):
        return None
    flag = lambda name, default="": argv[argv.index(name) + 1] if name in argv[:-1] else default
    workflow = next((w["name"] for w in saved_workflows() if env.get("COMFYUI_WORKFLOW") and w.get("path")
                     and os.path.normcase(os.path.abspath(w["path"])) == os.path.normcase(os.path.abspath(env["COMFYUI_WORKFLOW"]))), "")
    if env.get("COMFYUI_WORKFLOW") and not workflow:
        return None
    form = {"workflow": workflow, "prompt": item.get("prompt") or "", "seed": flag("--seed"),
            "prompt_mode": "direct" if "--direct" in argv else "llm", "llm": flag("--llm"),
            "size": flag("--size"), "review": "1" if "--plan-only" in argv or "--enhance-only" in argv else "",
            "try_first": "1" if "--first-only" in argv else ""}
    files = {}
    if pipeline == "video":
        form.update(duration=flag("--duration", "120"), clip_seconds=flag("--clip-seconds"), start=flag("--start", "chain"),
                    h3_enhance=flag("--h3-enhance", "off"), h3_creativity=flag("--h3-creativity", "balanced"),
                    audio_mode="file" if "--audio" in argv else "text" if "--narration" in argv else "none",
                    narration=flag("--narration"), voice=flag("--voice"))
        if "--fixed-clips" in argv:
            form["clip_fixed"] = "1"
        images = ([item["image"]] if item.get("image") else []) + [
            argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--reference"]
        for i, path in enumerate(images):
            files["image" if not i else f"image_{i + 1}"] = path
        image_roles = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--image-role"]
        form.update({f"image_{i + 2}_role": role for i, role in enumerate(image_roles)})
        if flag("--audio"):
            files["audio_file"] = flag("--audio")
        for kind in ("video", "audio"):
            for i, value in enumerate(argv[:-1]):
                if value == f"--ref-{kind}":
                    number = sum(name.startswith("ref_media") for name in files) + 1
                    name = "ref_media" if number == 1 else f"ref_media_{number}"
                    files[name] = argv[i + 1]
                    if i + 3 < len(argv) and argv[i + 2] == f"--ref-{kind}-role":
                        form[name + "_role"] = argv[i + 3]
        options = json.loads(env.get("COMFYUI_OPTIONS") or "{}")
    else:
        if "--areas" in argv:
            return None
        form.update(count=flag("--count", "1"), image_mode="compose" if "--compose" in argv else "expand" if "--expand" in argv else "edit",
                    aspect=flag("--aspect"), megapixels=flag("--megapixels"), detail=flag("--reference-detail"),
                    transparent="1" if "--transparent" in argv else "")
        for i, path in enumerate(argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--image"):
            files["image" if not i else f"image_{i + 1}"] = path
        options = dict(argv[i + 1].split("=", 1) for i, value in enumerate(argv[:-1]) if value == "--option" and "=" in argv[i + 1])
        if "--expand" in argv:
            for side, value in zip(("left", "top", "right", "bottom"), flag("--expand").split(",")):
                form[f"expand_{side}"] = value
            form["expand_units"] = "pixels"
    return form, files, options


def upscale_source_size(item):
    """[width, height] of what a queued upscale makes bigger, for the upscale box's "before → after"; None if unknown."""
    from panel import image as image_panel
    from PIL import Image
    argv = item.get("argv") or []
    flag = lambda name: argv[argv.index(name) + 1] if name in argv[:-1] else None
    try:
        if "pipelines.image.upscale" in argv:
            state = image_panel.RunState.load(item.get("resume"))
            position = image_panel.upscale_position(state, argv) if state else None
            if not position or not position.isdigit() or not 1 <= int(position) <= len(state.shots or []):
                return None
            with Image.open(state.image_path(state.shots[int(position) - 1])) as image:
                return list(image.size)
        if "pipelines.video.upscale" in argv and flag("--film"):
            path = os.path.join(FOLDERS["video"], flag("--film"))
            stat = os.stat(path)
            resolution = video_file_metadata(path, stat.st_mtime_ns, stat.st_size).get("resolution") or ""
            return [int(side) for side in resolution.split("x")] if "x" in resolution else None
    except (OSError, ValueError, TypeError):
        return None
    return None


def upscale_queue_settings(item):
    argv = item.get("argv") or []
    flag = lambda name, default="": argv[argv.index(name) + 1] if name in argv[:-1] else default
    if "pipelines.image.upscale" in argv and item.get("pipeline") == "image":
        return {"kind": "image_upscale", "method": flag("--method", "seedvr2"),
                "strength": flag("--strength", "1"), "resolution": flag("--resolution", "0"), "denoise": flag("--denoise")}
    if "pipelines.video.upscale" in argv and item.get("pipeline") == "video":
        return {"kind": "video_upscale", "scale": flag("--scale", "2"), "quality": flag("--quality")}
    return None


@app.route("/queue/run/edit/<int:item_id>", methods=["POST"])
@password_required
def queue_edit(item_id):
    with run_queue.lock:
        item = next((entry for entry in run_queue.items if entry["id"] == item_id), None)
        if not item:
            return {"ok": False, "error": "That job has already started or is no longer queued."}, 409
        upscale = upscale_queue_settings(item)
        continued = continued_setup(item) if item.get("resume") and not upscale else None
        if continued:
            # Its prompts are written: the setup opens as it was, to change how the rest is made, not what.
            item["edit_from_queue"] = not item.get("later")
            item["later"] = True
            item["edit_token"] = secrets.token_urlsafe(24)
            run_queue._save()
            return {"ok": True, "id": item_id, "token": item["edit_token"], "pipeline": item.get("pipeline"),
                    "form": continued["form"], "files": [], "filenames": {}, "options": {}, "continued": continued["run"]}
        if item.get("resume") and not upscale:
            return {"ok": False, "error": "Setup for a continued run cannot be edited here. The job was not changed."}, 409
        if upscale:
            # Where it was, Queue or Pending, so Cancel puts it back there.
            item["edit_from_queue"] = not item.get("later")
            item["later"] = True
            item["edit_token"] = secrets.token_urlsafe(24)
            run_queue._save()
            return {"ok": True, "id": item_id, "token": item["edit_token"], "pipeline": item.get("pipeline"),
                    "upscale": {**upscale, "size": upscale_source_size(item)}}
        restored = (item["form"], item.get("form_files", {}), {}) if item.get("form") else legacy_queue_form(item)
        if not restored:
            return {"ok": False, "error": "Setup is unavailable for this job. It remains in the queue unchanged."}, 409
        form, files, options = restored
        missing = [name for name, path in files.items() if not os.path.isfile(path)]
        if missing:
            return {"ok": False, "error": "A queued input file is missing. The job was not changed."}, 409
        item["edit_from_queue"] = not item.get("later")
        item["later"] = True
        item["edit_token"] = secrets.token_urlsafe(24)
        run_queue._save()
        return {"ok": True, "id": item_id, "token": item["edit_token"], "pipeline": item.get("pipeline"),
                "form": form, "files": list(files), "filenames": {name: os.path.basename(path) for name, path in files.items()}, "options": options}


# What can change for a run whose prompts are written: how the rest is made. Its prompt, images, length, workflow and
# LLM made those prompts, so they stay as they were.
CONTINUED_FIELDS = ("size", "aspect", "megapixels", "try_first")
CONTINUED_PREFIXES = ("opt_", "latent_upscale")


def continued_field(name):
    return name in CONTINUED_FIELDS or name.startswith(CONTINUED_PREFIXES)


def continued_form(saved, sent):
    """The run's form as it was made, with the fields that may change taken from what was sent now."""
    merged = MultiDict()
    for name, values in (saved or {}).items():
        if not continued_field(name):
            for value in values if isinstance(values, list) else [values]:
                merged.add(name, value)
    for name in sent:
        if continued_field(name):
            for value in sent.getlist(name):
                merged.add(name, value)
    return merged


def continued_setup(item):
    """A queued continuation's run as Edit opens it: its form and prompts. None when it can't be (no form kept, a redo)."""
    if item.get("pipeline") not in ("video", "image") or "--redo" in (item.get("argv") or []):
        return None
    state = PIPELINES[item["pipeline"]].load_run(item["resume"])
    if not state or not state.shots or not state.form:
        return None
    form = run_form.flat(state.form)
    # A preview run is the job's own choice, not the run's.
    form["try_first"] = "1" if "--first-only" in (item.get("argv") or []) else ""
    return {"form": form, "run": {"id": state.id, "title": state.title or state.brief, "image": item["pipeline"] == "image",
                                  "prompts": [shot.get("prompt") or "" for shot in state.shots]}}


@app.route("/queue/run/edit/<int:item_id>/continue", methods=["POST"])
@password_required
def queue_edit_continue(item_id):
    """Saves a continued run's changed setup (size, workflow options, a preview run) and puts it back in line."""
    token = request.form.get("queue_edit_token", "")
    with run_queue.lock:
        old = next((entry for entry in run_queue.items if entry["id"] == item_id), None)
        if not old or not old.get("edit_token") or not secrets.compare_digest(old["edit_token"], token):
            return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
        if not continued_setup(old):
            return {"ok": False, "error": "This job's setup cannot be edited."}, 409
        pipeline = PIPELINES[old["pipeline"]]
        state = pipeline.load_run(old["resume"])
        error = pipeline.edit_continuation(state, continued_form(state.form, request.form))
        if error:
            return {"ok": False, "error": error}, 400
        argv = pipeline.resume_argv(state)
        if request.form.get("try_first"):
            argv = argv + ["--first-only"]
        replacement = {**old, "argv": argv, "waited": True, "first_only": bool(request.form.get("try_first")),
                       "resolution": f"{state.width}x{state.height}",
                       # Its new size and options take another time: estimated again, as the run will be made.
                       "estimate": pipeline.estimate(argv, old.get("env") or {})}
        for key in ("later", "edit_token", "edit_from_queue"):
            replacement.pop(key, None)
        if request.form.get("start_later"):
            replacement["later"] = True
        else:
            run_queue._approve_prompt_warning(replacement)
        run_queue.items.remove(old)
        run_queue.items.insert(len(run_queue.items) if replacement.get("later") else 0, replacement)
        run_queue._save()
        run_queue._advance()
        _runs_cache["at"] = 0.0
        return {"ok": True, "queued": replacement in run_queue.items, "continued": state.title or state.brief}


@app.route("/queue/run/edit/<int:item_id>/upscale", methods=["POST"])
@password_required
def queue_edit_upscale(item_id):
    from panel import image as image_panel, video as video_panel
    from PIL import Image

    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not isinstance(token, str):
        return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
    with run_queue.lock:
        old = next((entry for entry in run_queue.items if entry["id"] == item_id), None)
        if not old or not old.get("edit_token") or not secrets.compare_digest(old["edit_token"], token):
            return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
        settings = upscale_queue_settings(old)
        if not settings:
            return {"ok": False, "error": "This job is not an upscale."}, 400
        argv = old["argv"]
        flag = lambda name: argv[argv.index(name) + 1] if name in argv[:-1] else None
        if settings["kind"] == "image_upscale":
            state = image_panel.RunState.load(old.get("resume"))
            position = image_panel.upscale_position(state, argv) if state else None
            if not state or not position or not position.isdigit() or not 1 <= int(position) <= len(state.shots or []):
                return {"ok": False, "error": "The original image is no longer available."}, 409
            shot = state.shots[int(position) - 1]
            if not shot.get("file"):
                return {"ok": False, "error": "The original image is no longer available."}, 409
            try:
                with Image.open(state.image_path(shot)) as source:
                    size = source.size
                    shorter = min(size)
            except OSError:
                return {"ok": False, "error": "The original image could not be read."}, 409
            method = data.get("method")
            try:
                strength = float(data.get("strength", 1))
                resolution = int(data.get("resolution", 0))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Choose a valid strength and resolution."}, 400
            if method not in image_panel.UPSCALE_METHODS or not math.isfinite(strength) or not 0 <= strength <= 1:
                return {"ok": False, "error": "Choose a valid upscale method and strength."}, 400
            problem = image_panel.upscale_problem(method, *size)
            if problem:
                return {"ok": False, "error": problem}, 400
            # A resolution offered, or what 2x, 3x or 4x made it (its shorter side times over, within SeedVR2's most).
            if (method == "seedvr2" and resolution and
                    ((resolution not in image_panel.UPSCALE_RESOLUTIONS and resolution > image_panel.SEEDVR2_MOST_EDGE)
                     or resolution <= shorter)):
                return {"ok": False, "error": "Choose a supported resolution larger than the original image."}, 400
            # 2x, 3x or 4x, as the upscale box says it: its shorter side that many times, within SeedVR2's most.
            times = data.get("times")
            if method == "seedvr2" and times:
                if str(times) not in tuple(str(n) for n in image_panel.UPSCALE_SCALES):
                    return {"ok": False, "error": "SeedVR2 makes it 2, 3 or 4 times its size."}, 400
                resolution = min(image_panel.SEEDVR2_MOST_EDGE, int(times) * shorter)
            if method != "seedvr2":
                resolution = 0
            denoise = None
            if method == "seedvr2":
                try:
                    denoise = image_panel.seedvr2_denoise(data.get("denoise")) or None
                except ValueError as e:
                    return {"ok": False, "error": str(e)}, 400
            if method in image_panel.REFINE_UPSCALES:
                try:
                    denoise = float(data.get("denoise") or 0.3)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "Denoise is a number from 0.05 to 1."}, 400
                if not math.isfinite(denoise) or not 0.05 <= denoise <= 1:
                    return {"ok": False, "error": "Denoise is a number from 0.05 to 1."}, 400
            how = image_panel.upscale_detail(method, strength, resolution, denoise, int(times) if method == "seedvr2" and times else None)
            new_argv = [*image_panel.UPSCALE, "--resume", state.id, "--image", position,
                        *(["--file", flag("--file")] if flag("--file") else []), "--method", method,
                        "--strength", f"{strength:g}", *(["--resolution", str(resolution)] if resolution else []),
                        *(["--denoise", f"{denoise:g}"] if denoise is not None else [])]
            estimate = UpscaleEta(new_argv, IMAGE_TIMINGS).plan()["total"]
        else:
            name = flag("--film")
            if not name:
                return {"ok": False, "error": "The original film is no longer available."}, 409
            try:
                video_panel.safe_video_path("video", name)
            except NotFound:
                return {"ok": False, "error": "The original film is no longer available."}, 409
            try:
                scale = float(data.get("scale"))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Choose a valid scale."}, 400
            quality = data.get("quality")
            if not math.isfinite(scale) or not 1 <= scale <= 4 or quality not in video_panel.film_upscale.QUALITIES:
                return {"ok": False, "error": "Choose a valid scale and quality."}, 400
            how = f"RTX VSR, {scale:g}x, {quality}"
            new_argv = [*video_panel.UPSCALE, "--film", name, "--scale", f"{scale:g}", "--quality", quality]
            estimate = UpscaleEta(new_argv, VIDEO_TIMINGS).plan()["total"]
        replacement = {**old, "argv": new_argv, "detail": how, "estimate": estimate, "waited": True}
        replacement.pop("later", None)
        replacement.pop("edit_token", None)
        run_queue.items.remove(old)
        run_queue.items.insert(0, replacement)
        run_queue._save()
        run_queue._advance()
        return {"ok": True, "queued": replacement in run_queue.items}


def queue_form_snapshot():
    return {name: values for name, values in request.form.to_dict(flat=False).items()
            if name not in ("queue_edit_id", "queue_edit_token", "start_later")}


@app.before_request
def validate_queue_edit():
    if not request.path.startswith("/generate/") or not request.form.get("queue_edit_id"):
        return None
    item_id = request.form.get("queue_edit_id", type=int)
    token = request.form.get("queue_edit_token", "")
    with run_queue.lock:
        item = next((entry for entry in run_queue.items if entry["id"] == item_id), None)
        if not item or item.get("pipeline") != request.path.rsplit("/", 1)[-1] or not item.get("edit_token") or not secrets.compare_digest(item["edit_token"], token):
            return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
    return None


@app.route("/queue/run/edit/<int:item_id>/file/<name>")
@password_required
def queue_edit_file(item_id, name):
    with run_queue.lock:
        item = next((entry for entry in run_queue.items if entry["id"] == item_id), None)
        if not item or not item.get("edit_token") or not secrets.compare_digest(item["edit_token"], request.headers.get("X-Queue-Edit-Token", "")):
            abort(404)
        restored = (item["form"], item.get("form_files", {}), {}) if item.get("form") else legacy_queue_form(item)
        path = restored[1].get(name) if restored else None
        if not path or not os.path.isfile(path):
            abort(404)
        return send_file(path, download_name=os.path.basename(path))


@app.route("/queue/run/edit/<int:item_id>/cancel", methods=["POST"])
@password_required
def queue_edit_cancel(item_id):
    token = (request.get_json(silent=True) or {}).get("token", "")
    with run_queue.lock:
        item = next((entry for entry in run_queue.items if entry["id"] == item_id), None)
        if not item or not item.get("edit_token") or not secrets.compare_digest(item["edit_token"], token):
            return {"ok": False, "error": "That editing session is no longer active."}, 409
        item.pop("edit_token")
        # Back where it came from: in the queue, at the place it held (its place in the list never changed), or in
        # Pending.
        if item.pop("edit_from_queue", False):
            item.pop("later", None)
        run_queue._save()
        run_queue._advance()
        return {"ok": True}


@app.route("/queue/<lane>/run-now/<int:item_id>", methods=["POST"])
@password_required
def queue_run_now(lane, item_id):
    if lane not in QUEUES:
        abort(404)
    if lane != "run":
        abort(404)
    result, error = QUEUES[lane].run_now(item_id)
    if result == "not_ready":
        return {"ok": False, "error": "Run this is available only while nothing is running."}, 409
    if result == "not_found":
        return {"ok": False, "error": "That job is no longer in the queue."}, 404
    if result == "failed":
        return {"ok": False, "error": error}, 500
    return {"ok": True}


@app.route("/queue/<lane>/order", methods=["POST"])
@password_required
def queue_order(lane):
    """The waiting jobs in a new order: {"ids": [...]}, first to start first."""
    if lane not in QUEUES:
        abort(404)
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return {"ok": False, "error": "The order is a list of the queued jobs' ids."}, 400
    return {"ok": True, "changed": QUEUES[lane].reorder(ids)}


@app.route("/queue/<lane>/resume", methods=["POST"])
@password_required
def queue_resume(lane):
    if lane not in QUEUES:
        abort(404)
    QUEUES[lane].resume()
    return {"ok": True}


@app.route("/queue/<lane>/hold", methods=["POST"])
@password_required
def queue_hold(lane):
    if lane not in QUEUES:
        abort(404)
    QUEUES[lane].hold()
    return {"ok": True}


@app.route("/api/settings", methods=["GET", "POST"])
@password_required
def api_settings():
    if request.method == "POST":
        changes = request.get_json(silent=True)
        if not isinstance(changes, dict):
            return {"ok": False, "error": "Settings are a JSON object."}, 400
        try:
            saved = settings.update(changes)
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        except OSError as e:
            return {"ok": False, "error": f"Could not save it: {e}"}, 500
        if "low_priority" in changes:
            threading.Thread(target=apply_comfyui_priority, daemon=True).start()
        return {"ok": True, "settings": saved}
    return {"ok": True, "settings": settings.load(), "local_models": settings.local_models(), "disk": disk_usage()}


@app.route("/api/local-models")
@password_required
def api_local_models():
    return {"ok": True, "models": settings.local_models()}


@app.route("/api/write-prompt", methods=["GET", "POST"])
@password_required
def write_prompt():
    from core import h3_refiner
    from google.genai.errors import APIError

    if request.method == "GET":
        side = request.args.get("pipeline")
        writer = request.args.get("writer") or "local"
        if side not in ("image", "video"):
            return {"ok": False, "error": "Choose an image or video prompt."}, 400
        if writer not in ("local", "gemini", "prompt_enhancer") or (writer == "prompt_enhancer" and side != "image"):
            return {"ok": False, "error": "Choose a prompt writer supported for this generation setup."}, 400
        if writer == "gemini" and not os.getenv("GEMINI_API_KEY"):
            return {"ok": False, "error": "Gemini has no API key in .env."}, 400
        try:
            model = (request.args.get("model") or h3_refiner.local_llm_model()) if writer == "local" else writer.replace("_", "-")
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 500
        if writer == "local" and model not in {item["id"] for item in settings.local_models()}:
            return {"ok": False, "error": "Choose a local prompt model available in Settings."}, 400
        timings = eta_keys.Timings(PROMPT_WRITER_TIMINGS, {})
        # Kept loaded, it skips the start: timed apart, the cold time standing in until it has been.
        cold = f"{model} | {side}"
        estimate = timings.step([cold + " | warm", cold] if writer == "local" and warm_model() == model else cold)
        if estimate is not None and (not math.isfinite(estimate) or estimate <= 0):
            app.logger.warning("Invalid prompt writer timing for %s / %s: %s", model, side, estimate)
            estimate = None
        default = (300 if settings.model_family(model) == "qwen3-14b" else 180) if writer == "local" else (180 if writer == "prompt-enhancer" else 45)
        return {"ok": True, "writer": writer, "model": model, "seconds": estimate if estimate is not None else default}
    data = request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(data, dict) or data.get("pipeline") not in ("image", "video"):
        return {"ok": False, "error": "Choose an image or video prompt."}, 400
    text = data.get("prompt")
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        return {"ok": False, "error": "Enter a prompt of up to 16,000 characters."}, 400
    writer = data.get("writer") or "local"
    side = data["pipeline"]
    if writer not in ("local", "gemini", "prompt_enhancer") or (writer == "prompt_enhancer" and side != "image"):
        return {"ok": False, "error": "Choose a prompt writer supported for this generation setup."}, 400
    if writer == "gemini" and not os.getenv("GEMINI_API_KEY"):
        return {"ok": False, "error": "Gemini has no API key in .env."}, 400
    if writer == "local":
        try:
            model = data.get("model") or h3_refiner.local_llm_model()
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 500
        if model not in {item["id"] for item in settings.local_models()}:
            return {"ok": False, "error": "Choose a local prompt model available in Settings."}, 400
    else:
        model = writer.replace("_", "-")
    global _writing_prompt, _prompt_refiner
    with run_queue.lock:
        if _writing_prompt or _panel_closing or _comfy_restarting or _comfy_freeing or job.running or (run_queue.pending() and not run_queue.held):
            return {"ok": False, "error": "Wait for the current generation or prompt writer to finish."}, 409
        _writing_prompt = True
    warm = False
    try:
        started = time.monotonic()
        if writer == "local":
            refiner = take_warm(model)
            warm = refiner is not None
            if warm:
                # Something may have used ComfyUI since (its own page): it lets go of what it loaded again first.
                try:
                    refiner._release_comfy_models()
                except BaseException:
                    refiner.__exit__(None, None, None)
                    raise
            else:
                url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
                # Writing from words alone: no vision projector, which leaves its memory to the model.
                refiner = h3_refiner.Refiner(url, require_compiler=False, model_id=model, vision=False)
                if refiner.model_id != model:
                    return {"ok": False, "error": "The selected model changed. Try writing the prompt again."}, 409
            with run_queue.lock:
                _prompt_refiner = refiner
            try:
                if not warm:
                    refiner.__enter__()
                prompt = refiner.write_prompt(text.strip(), side)
            except BaseException:
                refiner.__exit__(None, None, None)
                raise
            keep_warm(refiner)
        elif writer == "gemini":
            from google.genai import types
            from core import gemini, prompt_writer_instructions
            response = gemini._generate(
                text.strip(),
                config=types.GenerateContentConfig(system_instruction=prompt_writer_instructions.INSTRUCTIONS[side]))
            prompt = getattr(response, "text", None)
            if not isinstance(prompt, str) or not prompt.strip():
                raise RuntimeError("Gemini returned an empty prompt.")
            prompt = prompt.strip()
        else:
            # The workflow's enhancer runs in ComfyUI, which needs the memory a warm local model holds.
            close_warm_writer()
            from panel import image as image_panel
            from pipelines.image.comfy import ImageClient
            uploads = image_panel.form_uploads(request.files)
            env, takes, error = image_panel.chosen_workflow(request.form, len(uploads))
            if error:
                return {"ok": False, "error": error}, 400
            enhancer = next((option for option in takes.get("options", []) if option.get("id") == "prompt_enhancer"), None)
            if not enhancer:
                return {"ok": False, "error": "The selected image workflow has no prompt enhancer."}, 400
            if enhancer.get("problem"):
                return {"ok": False, "error": f"{enhancer['label']} can't run: {enhancer['problem']}"}, 400
            if not takes["min_images"] <= len(uploads) <= takes["max_images"]:
                return {"ok": False, "error": "Choose the number of source images this workflow needs."}, 400
            workflow_path = env.get("COMFYUI_WORKFLOW")
            if not workflow_path:
                return {"ok": False, "error": "Choose an image workflow with a prompt enhancer."}, 400
            options, error = form_options(request.form, takes)
            if error:
                return {"ok": False, "error": error}, 400
            options["prompt_enhancer"] = "1"
            comfy = ImageClient(options, workflow_path=workflow_path)
            if not comfy.wait_until_reachable():
                raise RuntimeError(f"ComfyUI isn't running at {comfy.url}. Start it first.")
            images = []
            for upload in uploads:
                try:
                    video_media.load_image(upload.stream)
                except RuntimeError:
                    return {"ok": False, "error": "That file isn't an image this can read."}, 400
                upload.stream.seek(0)
                extension = os.path.splitext(upload.filename)[1].lower()
                extension = extension if re.fullmatch(r"\.[a-z0-9]{1,5}", extension) else ""
                images.append(comfy._send_image(upload.stream, f"prompt-editor-{secrets.token_hex(8)}{extension}"))
            prompt = comfy.enhance(text.strip(), images)
            if not prompt or not prompt.strip():
                raise RuntimeError("The workflow's prompt enhancer returned no text.")
        timings = eta_keys.Timings(PROMPT_WRITER_TIMINGS, {})
        key = f"{model} | {side}" + (" | warm" if warm else "")
        old = timings.timed_step(key)
        if old is not None and (not math.isfinite(old) or old <= 0):
            app.logger.warning("Discarding invalid prompt writer timing for %s: %s", key, old)
            timings.timed_steps.discard(key)
        timings.learn_step(key, time.monotonic() - started)
        try:
            os.makedirs(os.path.dirname(PROMPT_WRITER_TIMINGS), exist_ok=True)
            temporary = PROMPT_WRITER_TIMINGS + ".tmp"
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump(timings.as_dict(), file, indent=2)
            os.replace(temporary, PROMPT_WRITER_TIMINGS)
        except OSError as e:
            app.logger.warning("Could not save local prompt writer timings: %s", e)
        return {"ok": True, "prompt": prompt}
    except (RuntimeError, OSError, ValueError, APIError) as e:
        return {"ok": False, "error": str(e)}, 500
    finally:
        with run_queue.lock:
            _writing_prompt = False
            _prompt_refiner = None
        run_queue._advance_locked()


_disk_cache = {"at": 0.0, "value": None}


def disk_usage():
    """The disk the videos and images go to: what's free, and what the three output folders take."""
    if _disk_cache["value"] and time.time() - _disk_cache["at"] < 30:
        return _disk_cache["value"]
    folder = FOLDERS["output"]
    while folder and not os.path.exists(folder) and os.path.dirname(folder) != folder:
        folder = os.path.dirname(folder)
    try:
        usage = shutil.disk_usage(folder)
    except OSError:
        return None
    used = 0
    for root in {os.path.abspath(path) for path in FOLDERS.values()}:
        for where, _, names in os.walk(root):
            for name in names:
                try:
                    used += os.path.getsize(os.path.join(where, name))
                except OSError:
                    pass
    value = {"free": usage.free, "total": usage.total, "outputs": used,
             "drive": os.path.splitdrive(os.path.abspath(folder))[0] or "/"}
    _disk_cache.update(at=time.time(), value=value)
    return value


POWEROFF_IDLE = 15   # Seconds with nothing to do before the PC is told to shut down: a gap between two jobs isn't the end.
POWEROFF_POLL = 3
POWEROFF_GRACE = 60  # Seconds Windows waits, in which turning the option off (or new work) cancels it.
_poweroff = {"armed": False, "at": None, "idle_since": None}
_poweroff_lock = threading.Lock()


def _shutdown_command(cancel=False):
    if os.name == "nt":
        return ["shutdown", "/a"] if cancel else ["shutdown", "/s", "/t", str(POWEROFF_GRACE)]
    return ["shutdown", "-c"] if cancel else ["shutdown", "-h", f"+{max(1, POWEROFF_GRACE // 60)}"]


def _run_shutdown(cancel=False):
    try:
        subprocess.run(_shutdown_command(cancel), creationflags=NO_WINDOW, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def poweroff_state():
    with _poweroff_lock:
        left = max(0, round(_poweroff["at"] - time.time())) if _poweroff["at"] else None
        return {"armed": _poweroff["armed"], "seconds_left": left}


def _poweroff_loop():
    """While armed: once everything has been done for a moment, shuts the PC down. Not saved: a new server starts unarmed."""
    while True:
        time.sleep(POWEROFF_POLL)
        with _poweroff_lock:
            if not _poweroff["armed"]:
                _poweroff["watching"] = False
                return
            busy = bool(work_left())
            if busy:
                _poweroff["idle_since"] = None
                if _poweroff["at"]:
                    _poweroff["at"] = None
                    _run_shutdown(cancel=True)
            elif _poweroff["at"] is None:
                _poweroff["idle_since"] = _poweroff["idle_since"] or time.time()
                if time.time() - _poweroff["idle_since"] >= POWEROFF_IDLE:
                    _poweroff["at"] = time.time() + POWEROFF_GRACE
                    _run_shutdown()


@app.route("/api/poweroff", methods=["GET", "POST"])
@password_required
def api_poweroff():
    """Shut the PC down once the queue is empty: for this session only, so it is never saved."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        arm = bool(body.get("armed"))
        with _poweroff_lock:
            was_counting = _poweroff["at"] is not None
            _poweroff.update(armed=arm, idle_since=None, at=None if not arm else _poweroff["at"])
            if arm and not _poweroff.get("watching"):
                _poweroff["watching"] = True
                threading.Thread(target=_poweroff_loop, daemon=True).start()
            if not arm:
                _poweroff["at"] = None
        if not arm and was_counting:
            _run_shutdown(cancel=True)
    return {"ok": True, **poweroff_state()}


def respawn_command():
    """What starts this server again as it was started: the helper waits for the port to be let go first."""
    code = ("import json,subprocess,sys,time;time.sleep(2);a=json.loads(sys.argv[1]);"
            "subprocess.Popen(a['argv'],cwd=a['cwd'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
            "stderr=subprocess.DEVNULL,creationflags=a['flags'])")
    flags = NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return [sys.executable, "-c", code, json.dumps({"argv": [sys.executable, *sys.argv], "cwd": PROJECT_ROOT, "flags": flags})], flags


@app.route("/restart/panel", methods=["POST"])
@password_required
def restart_panel():
    """Starts the panel again, to load new code. Only when nothing is running that it would cut short."""
    global _panel_closing
    with run_queue.lock:
        if restart_blocked():
            return {"ok": False, "error": "A run, upload or prompt writer is going, or a queue is about to start one. Wait for it first."}, 409
        command, flags = respawn_command()
        subprocess.Popen(command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
        _panel_closing = True
        exit_soon()
    return {"ok": True}


def restart_comfyui_now():
    for process in comfyui_processes():
        kill_tree(process.pid)
    close_comfyui()
    for _ in range(20):
        _comfyui_cache["at"] = 0.0
        if not comfyui_online():
            break
        time.sleep(0.5)
    global _comfyui_start_requested_at
    _comfyui_start_requested_at = 0.0
    try:
        start_comfyui()
    except RuntimeError as e:
        job.log(f"⚠️ {e}")



@app.route("/restart/comfyui", methods=["POST"])
@password_required
def restart_comfyui():
    """
    Closes ComfyUI and starts it again. Not while a run or prompt writer is going, unless the body says force: then at
    once, whatever the panel believes is going (that run fails, and is tried once more: restart_reason).
    """
    force = bool((request.get_json(silent=True) or {}).get("force"))
    with run_queue.lock:
        if not force and (job.running or _writing_prompt or _comfy_restarting or _comfy_freeing):
            return {"ok": False, "error": "A run or prompt writer is going, or ComfyUI is restarting. Wait for it first."}, 409
        if not comfyui_launcher():
            return {"ok": False, "error": "COMFYUI_LAUNCHER isn't set in .env, so the panel can't start ComfyUI again."}, 400
        if force and job.running:
            job.log("⚠️ ComfyUI was force-restarted from Settings while this was running.")
        restart_comfyui_in_background(force=force)
    return {"ok": True}


@app.route("/shutdown", methods=["POST"])
@password_required
def shutdown():
    """
    Force-stops everything the panel is doing, then the server itself: started
    from start_webapp.pyw it has no window to close.
    """
    global _panel_closing
    with run_queue.lock:
        if _writing_prompt:
            return {"ok": False, "error": "Wait for the prompt writer to finish before shutting down."}, 409
        for queue in QUEUES.values():
            queue.close()
        _panel_closing = True
    stop_run()
    uploads.stop()
    # Exiting now would leave it running with nothing in the panel to stop it.
    if job.running or uploads.running:
        return {"ok": False, "error": f"{STOP_FAILED} Then shut down again."}, 500
    close_comfyui()
    # Reply first, then exit, so the browser gets its answer.
    exit_soon()
    return {"ok": True}


@app.route("/launcher/refresh", methods=["POST"])
def launcher_refresh():
    """
    Exits if the code changed after this server started, so start_webapp.pyw can
    start a fresh one. Only answers this PC, and never stops a run or a queue that's going.
    """
    if not on_this_pc():
        abort(403)
    try:
        code_changed_at = float(request.form.get("code_changed_at", 0))
    except ValueError:
        abort(400)
    global _panel_closing
    with run_queue.lock:
        if code_changed_at <= STARTED_AT or restart_blocked():
            return {"restarting": False}
        _panel_closing = True
        exit_soon()
    return {"restarting": True}


_catalogue_cache = CatalogueCache()


@app.after_request
def invalidate_output_catalogue(response):
    if request.method not in ("GET", "HEAD", "OPTIONS") and response.status_code < 400:
        _catalogue_cache.invalidate()
    return response


def _scan_output_catalogue():
    return {
        "videos": {folder: list_videos(folder) for folder in FOLDERS},
        "image_sets": [run for run in saved_runs() if run["pipeline"] == "image" and run["images"]],
    }, films_of_runs()


@app.route("/api/status")
@password_required
def status():
    return status_payload(request.args.get("catalogue_revision"), request.args.get("log_after", type=int))


def status_payload(catalogue_revision=None, log_after=None):
    """
    The page's status. With the revision of the Output catalogue the page has, the catalogue only when it changed; with
    the last log line it has, the log from there.
    """
    payload, queue = run_queue.snapshot_with_job()
    with run_queue.lock:
        payload["prompt_writer"] = {"running": _writing_prompt,
                                    "tokens": _prompt_refiner.tokens if _prompt_refiner is not None else None}
    run_id = (payload.get("progress") or {}).get("run_id")
    if queue.get("current") and run_id and payload.get("pipeline") in ("image", "video"):
        state = PIPELINES[payload["pipeline"]].load_run(run_id)
        if state and getattr(state, "width", None) and getattr(state, "height", None):
            queue["current"]["facts"]["resolution"] = f"{state.width}x{state.height}"
    payload["server_started"] = STARTED_AT
    payload["stop_after"] = payload["running"] and batch_stop.requested()
    payload["cancelling"] = bool(payload["running"] and _cancelling["started_at"] and _cancelling["started_at"] == job.started_at)
    payload["queue"] = queue
    payload["stopped_runs"] = stopped_runs()
    payload["made_now"] = made_in_this_run()
    payload["upload"] = uploads.snapshot()
    payload["upload"]["queue"] = upload_queue.snapshot()
    compact = catalogue_revision is not None
    if compact:
        catalogue, film_runs, scanned_revision = _catalogue_cache.get(_scan_output_catalogue, active=payload["running"])
        payload.update(copy.deepcopy(catalogue))
        for run in payload["image_sets"]:
            run["generating"] = bool(payload["running"] and payload.get("pipeline") == "image" and run["id"] == run_id)
    else:
        payload["videos"] = {folder: list_videos(folder) for folder in FOLDERS}
        payload["image_sets"] = [{**run, "generating": bool(payload["running"] and payload.get("pipeline") == "image"
                                                            and run["id"] == run_id)}
                                 for run in saved_runs() if run["pipeline"] == "image" and run["images"]]
        film_runs = films_of_runs()
    with _nsfw_lock:
        tags = _read_nsfw()
    payload["private"] = private_mode()
    payload["output_order"] = settings.load()["output_order"]
    _current_films(payload["queue"]["results"], film_runs)
    _apply_nsfw(payload, tags, film_runs, payload["private"])
    for hook in STATUS_HOOKS:
        try:
            hook(payload)
        except Exception as e:  # The status is polled for the whole page: one part failing must not freeze it
            app.logger.error("Status could not be completed: %s", e)
    online = comfyui_online(wait=False)
    payload["comfyui"] = {"online": online, "listening": comfyui_listening(), "can_start": bool(comfyui_launcher()), "ram": ram_stats(),
                          "starting": not online and time.time() - _comfyui_start_requested_at < COMFYUI_STARTUP_WAIT,
                          "restarting": _comfy_restarting,
                          **(comfy_monitor.snapshot() if comfy_monitor else {})}
    payload["gpu"] = gpu_stats()
    payload["poweroff"] = poweroff_state()
    payload["quota"] = cached_quota()
    payload["checkpoint_errors"] = [
        {**error, **({"run_id": target[1]} if (target := checkpoint_target(error)) else {})}
        for error in catalogue_errors()
    ]
    if compact:
        revision = hashlib.sha256(json.dumps(
            [scanned_revision, tags, payload["private"], payload["output_order"], payload.get("collections", [])],
            sort_keys=True,
        ).encode()).hexdigest()
        payload["catalogue_revision"] = revision
        if catalogue_revision == revision:
            for key in ("videos", "image_sets", "collections", "output_order"):
                payload.pop(key, None)
    _only_new_log_lines(payload, log_after)
    return payload


# The status pushed to the page (Server-Sent Events): as soon as something changes, and at least this often, for the
# clock, the GPU and the ETA. Before, the page asked every 2 seconds, so a change took up to 2 seconds to show.
STREAM_EVERY = 2.0
# Changes that come in a burst (log lines one after another) go in one update.
STREAM_GATHER = 0.25


@app.route("/api/status/stream")
@password_required
def status_stream():
    revision = request.args.get("catalogue_revision", "")
    log_after = request.args.get("log_after", type=int)

    def events():
        nonlocal revision, log_after
        # Lost (the panel restarting), the browser connects again after this long.
        yield "retry: 2000\n\n"
        while not _panel_closing:
            seen = status_version()
            payload = status_payload(revision, log_after)
            revision = payload.get("catalogue_revision", revision)
            if payload["lines"]:
                log_after = payload["lines"][-1]["n"]
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            wait_for_status_change(seen, STREAM_EVERY)
            time.sleep(STREAM_GATHER)

    response = Response(stream_with_context(events()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def _only_new_log_lines(payload, log_after):
    """
    The log from the line the page last has, not all of it: the whole log, up to 2000 lines, sent every 2 seconds
    made each status about 280 KB, which a phone away from home couldn't fetch in time, so it showed the panel as
    disconnected. That line is sent again because its ETA can be added just after it is logged. Without it (a new job
    started a new log, or the page has none yet), the whole log is sent, and log_delta is False.
    """
    lines = payload.setdefault("lines", [])
    payload["log_first"] = lines[0]["n"] if lines else None
    payload["log_delta"] = log_after is not None and any(line["n"] == log_after for line in lines)
    if payload["log_delta"]:
        payload["lines"] = [line for line in lines if line["n"] >= log_after]


# Gzipped only when worth it: a status without the Output catalogue is a few KB.
GZIP_FROM_BYTES = 2048


@app.after_request
def gzip_json(response):
    """
    Large JSON goes compressed (the status with the Output catalogue: about 600 KB, 10 times smaller gzipped), so a
    phone on mobile data or Tailscale gets it within the poll's time limit.
    """
    if (response.mimetype != "application/json" or response.direct_passthrough or response.status_code < 200
            or response.status_code >= 300 or "Content-Encoding" in response.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "").lower()):
        return response
    data = response.get_data()
    if len(data) < GZIP_FROM_BYTES:
        return response
    response.set_data(gzip.compress(data, compresslevel=5))
    response.headers["Content-Encoding"] = "gzip"
    response.headers.add("Vary", "Accept-Encoding")
    return response


def _shown(value):
    """An input as the workflow viewer says it: a link to another node's output, or the value itself, cut if long."""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
        return f"→ node {value[0]}" + (f" (output {value[1]})" if value[1] else "")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 400 else text[:400] + "…"


@app.route("/api/run-workflow")
@password_required
def run_workflow():
    """
    The workflow the current or last run renders with, as it is sent to ComfyUI with that run's options: which options
    were set, and every node with what it is given. For the page's Workflow view.
    """
    started = job.workflow
    if not started:
        return {"error": "Nothing has run yet."}, 404
    path, chosen, pipeline = started.get("path"), started.get("options") or {}, started.get("pipeline")
    if not path and pipeline == "video":
        path = video_comfy.DEFAULT_WORKFLOW
    if not path:
        return {"error": "This run uses the built-in workflow, which isn't a saved one."}, 404
    api = None
    if chosen:
        try:
            api = workflow_options.remake(path, chosen, pipeline)[0]
        except RuntimeError:
            api = None
    if api is None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                api = json.load(f)
        except (OSError, ValueError):
            return {"error": "That workflow's file is gone."}, 404
    try:
        with open(os.path.splitext(path)[0] + ".map.json", "r", encoding="utf-8") as f:
            offered = json.load(f).get("_options") or []
    except (OSError, ValueError):
        offered = []
    options = [{"label": option["label"], "value": chosen.get(option["id"], option["default"]), "changed": option["id"] in chosen}
               for option in offered if not option.get("role")]
    nodes = [{"id": node_id, "type": node.get("class_type", ""), "inputs": {name: _shown(value) for name, value in node.get("inputs", {}).items()}}
             for node_id, node in sorted(api.items(), key=lambda item: (not item[0].isdigit(), int(item[0]) if item[0].isdigit() else 0, item[0]))]
    return {"name": display_label(os.path.basename(path)), "pipeline": pipeline, "options": options, "nodes": nodes,
            "running": job.running, "api": api}


PRESETS_PATH = os.path.join(LOGS_DIR, "presets.json")
PRESET_SIDES = ("shorts", "video", "image")
MOST_PRESET_NAME = 60


def load_presets():
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return {side: [p for p in saved.get(side, []) if isinstance(p, dict) and p.get("name")] for side in PRESET_SIDES}
    except (OSError, ValueError, AttributeError):
        return {side: [] for side in PRESET_SIDES}


@app.route("/api/page-error", methods=["POST"])
@password_required
def page_error():
    """A part of the page that threw while updating, from a phone's browser: into the panel's own log, to be found."""
    error = str((request.get_json(silent=True) or {}).get("error") or "")[:1500]
    logging.getLogger("werkzeug").warning("Page error from %s: %s", request.remote_addr, error)
    # Kept on disk too: the panel runs without a console, so the log above is read by no one.
    try:
        with open(os.path.join(LOGS_DIR, "page_errors.log"), "a", encoding="utf-8") as log:
            log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {request.remote_addr} {error}\n")
    except OSError:
        pass
    return {"ok": True}


@app.route("/api/presets", methods=["GET", "POST"])
@password_required
def presets():
    """A side's settings under a name: kept here, so every device has the same ones. POST saves one, deletes it, or makes it the default."""
    if request.method == "GET":
        return {"ok": True, "presets": load_presets()}
    body = request.get_json(silent=True) or {}
    side, name = body.get("side"), str(body.get("name") or "").strip()[:MOST_PRESET_NAME]
    if side not in PRESET_SIDES or not name:
        return {"ok": False, "error": "A preset needs a side and a name."}, 400
    saved = load_presets()
    if "default" in body and "values" not in body and not body.get("delete"):
        # The side's default, set as the page opens: one at most, so making one the default unmakes the last.
        if not any(p["name"] == name for p in saved[side]):
            return {"ok": False, "error": "There is no preset of that name."}, 404
        for p in saved[side]:
            p.pop("default", None)
            if body["default"] and p["name"] == name:
                p["default"] = True
    else:
        old = next((p for p in saved[side] if p["name"] == name), {})
        kept = [p for p in saved[side] if p["name"] != name]
        if not body.get("delete"):
            values = body.get("values")
            if not isinstance(values, dict):
                return {"ok": False, "error": "A preset needs its settings."}, 400
            # Saved over, it stays the default if it was one.
            kept.append({"name": name, "values": {str(k): v for k, v in values.items() if isinstance(v, (str, bool, int, float))},
                         **({"default": True} if old.get("default") else {})})
        saved[side] = sorted(kept, key=lambda p: p["name"].casefold())
    try:
        os.makedirs(os.path.dirname(PRESETS_PATH), exist_ok=True)
        with open(PRESETS_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False, indent=1)
        os.replace(PRESETS_PATH + ".tmp", PRESETS_PATH)
    except OSError as e:
        return {"ok": False, "error": f"Could not save it: {e}"}, 500
    return {"ok": True, "presets": saved}


@app.route("/api/workflows")
@password_required
def workflows():
    """
    What runs on this pipeline. logs/workflows/not_listed.json says why anything else isn't here.
    Image also lists what can't run, with why: it has no built-in workflow to fall back on, so an empty list says nothing.
    """
    pipeline = request.args.get("pipeline") or "video"
    found = [{key: w[key] for key in ("name", "label", "takes", "problem") if key in w} for w in saved_workflows()
             if w.get("pipeline", pipeline_of(w["name"])) == pipeline and (pipeline == "image" or "problem" not in w)]
    # The image_, video_ or shorts_ in front only sorts them in ComfyUI: here the side already says it.
    for w in found:
        w["label"] = display_label(w["label"])
    paths_by_name = {w["name"]: w.get("path") for w in saved_workflows()}
    for w in found:
        guide = model_guide.entry(model_guide.key_for_path(paths_by_name.get(w["name"]), pipeline))
        if guide:
            w["guide"] = guide
    if pipeline == "video":
        # How long its video model makes a clip, for the form to say.
        paths = {w["name"]: w.get("path") for w in saved_workflows()}
        for w in found:
            model = workflow_model(paths.get(w["name"]))
            w["clip_seconds"] = video_planner.clip_seconds(model)
            from core import h3_refiner
            from pipelines.video import h3_multishot
            from core import director
            w["openh3"] = h3_refiner.supports_path(paths.get(w["name"]))
            w["h3_multishot"] = h3_multishot.supports_path(paths.get(w["name"]))
            try:
                with open(paths.get(w["name"]) or "", encoding="utf-8") as file:
                    graph = json.load(file)
                w["h3_director"] = (director.INPUTS_ID in graph and
                                     graph[director.INPUTS_ID].get("class_type") == director.INPUTS)
            except (OSError, ValueError, AttributeError):
                w["h3_director"] = False
            if video_media.most_pixels(model):
                w["most_pixels"] = video_media.most_pixels(model)
    elif pipeline == "shorts":
        paths = {w["name"]: w.get("path") for w in saved_workflows()}
        for w in found:
            w["openh3"] = workflow_model(paths.get(w["name"])) == "minimax_h3"
    return {"online": comfyui_online(), "workflows": found, "built_in_guide": model_guide.entry(model_guide.BUILT_IN.get(pipeline))}


@app.route("/api/model-guide/<key>")
@password_required
def api_model_guide(key):
    """The guide to one diffusion model, for the link under the workflow picker."""
    found = model_guide.guide(key)
    if not found:
        abort(404)
    return {"ok": True, "guide": found}


@app.route("/comfyui/start", methods=["POST"])
@password_required
def comfyui_start():
    """A manual start replaces any local ComfyUI instance; automatic starts don't."""
    with run_queue.lock:
        if restart_blocked():
            return {"ok": False, "error": "A run or upload is going, or a queue is about to start one. Stop it or let it finish first."}, 409
        try:
            start_fresh_comfyui()
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}, 500
    return {"ok": True}


@app.route("/videos/<folder>/<path:name>")
@password_required
def video_file(folder, name):
    return send_file(safe_video_path(folder, name), mimetype="video/mp4", conditional=True)


@app.route("/posters/<folder>/<path:name>")
@password_required
def poster(folder, name):
    """The picture a Short shows before it plays, as videos only load once you press play."""
    stem = os.path.splitext(safe_video_path(folder, name))[0]
    for candidate in (f"{stem}.jpg", f"{stem}.still.jpg"):
        if os.path.exists(candidate):
            return send_file(candidate, mimetype="image/jpeg", max_age=3600)
    abort(404)


@app.route("/download/<folder>/<path:name>")
@password_required
def download(folder, name):
    return send_file(safe_video_path(folder, name), as_attachment=True, download_name=name)


@app.route("/folders/<folder>/open", methods=["POST"])
@password_required
def open_folder(folder):
    """Shows a tab's folder in File Explorer. Made here if need be: nothing has been uploaded at first."""
    if not can_open_folders():
        abort(403)
    if folder not in FOLDERS:
        abort(404)
    try:
        os.makedirs(FOLDERS[folder], exist_ok=True)
        os.startfile(FOLDERS[folder])
    except OSError as e:
        return {"ok": False, "error": f"Could not open the folder: {e}"}, 500
    return {"ok": True}


@app.route("/delete/<folder>/<path:name>", methods=["POST"])
@password_required
def delete(folder, name):
    path = safe_video_path(folder, name)
    film = os.path.basename(path)
    # Which run made it, asked before the run goes with it; an upscaled copy is only itself.
    run_id = None
    if FOLDER_PIPELINES.get(folder) == "video":
        run_id = None if UPSCALED.search(film) else run_of_film(film)
    reply = PIPELINES[FOLDER_PIPELINES.get(folder, "shorts")].delete_video(folder, path)
    body = reply[0] if isinstance(reply, tuple) else reply
    if isinstance(body, dict) and body.get("ok"):
        # Deleted from Output, it is gone from Finished too.
        for queue in QUEUES.values():
            queue.forget(run_id=run_id, film=film)
    return reply


@app.after_request
def never_cache_status(response):
    if request.path == "/api/status":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.after_request
def log_refused_generate(response):
    """A Generate the panel turned down says why in the log, where it can still be read once the page has moved on."""
    if request.path.startswith("/generate/") and response.status_code >= 400 and response.is_json:
        error = (response.get_json(silent=True) or {}).get("error")
        if error:
            job.log(f"{REFUSED} Not added ({request.path.rsplit('/', 1)[-1]}): {error}")
    return response


class _QuietPolling(logging.Filter):
    """Drops the access-log line for the page's 2-second status poll, which would bury everything else."""

    def filter(self, record):
        return "/api/status" not in record.getMessage()


def connect_tailscale(port):
    url, problem = tailscale.connect(port)
    if url:
        print(f"🌍 Anywhere:   {url}  (Tailscale)")
    elif problem:
        print(f"⚠️ {problem} Your phone can only reach the panel at home until it connects.")


def main():
    # Started with its output thrown away (the restart does), Python writes in the console's code page, which has no emoji.
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.getLogger("werkzeug").addFilter(_QuietPolling())

    parser = argparse.ArgumentParser(description="The gen-center panel.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1; 0.0.0.0 for your phone).")
    parser.add_argument("--port", type=int, default=8800, help="Port (default: 8800).")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.host != "127.0.0.1" and not os.getenv("APP_PASSWORD"):
        parser.error(
            "Refusing to listen on a public address without APP_PASSWORD set. "
            "Anyone who finds the URL could spend your API quota and GPU. "
            "Set APP_PASSWORD in your .env and try again."
        )

    if not os.getenv("FLASK_SECRET_KEY"):
        print("⚠️ FLASK_SECRET_KEY not set — using a random key, so logins drop on restart.")

    # The Werkzeug reloader parent only supervises its child; the child owns the panel.
    owns_panel = not args.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if owns_panel:
        if not PANEL_OWNER.acquire():
            parser.error(PANEL_OWNER.error)
        for queue in QUEUES.values():
            queue._activate()
        for hook in STARTUP_HOOKS:
            try:
                hook()
            except Exception as e:  # Tidying up must never keep the panel from starting
                app.logger.error("A start-up task failed: %s", e)

    global comfy_monitor
    comfy_monitor = ComfyMonitor()

    print(f"🌐 This PC:    http://127.0.0.1:{args.port}")
    if args.host == "0.0.0.0":
        print(f"📱 Your phone: http://{lan_ip()}:{args.port}  (or http://{socket.gethostname()}.local:{args.port})")
        # In the background: it can take a while, and the panel shouldn't wait for it.
        threading.Thread(target=connect_tailscale, args=(args.port,), daemon=True).start()
    print("   Stop it with 'Shut down' in the panel (or close this window if it has one).")
    try:
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    finally:
        if owns_panel:
            PANEL_OWNER.release()
