import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from core import run_checkpoint
from core.saved_run import SavedRun
from core.paths import WORKFLOWS_DIR
from pipelines.shorts.paths import RUNS_DIR

# Same order as main.py's STAGES, which can't be imported here: it pulls in the whole pipeline.
STAGES = ("Topic & script", "Voice", "Stock footage", "Avatar clips", "Rendering scenes", "Stitching", "Upload")
# What the panel sets per run rather than on the command line. A continued run keeps them.
RUN_ENV = ("AVATAR_SOURCE", "AVATAR_SIZE", "COMFYUI_WORKFLOW", "COMFYUI_OPTIONS", "AVATAR_CLIPS_MIN", "AVATAR_CLIPS_MAX",
           "AVATAR_MIN_SECONDS", "AVATAR_MAX_SECONDS", "H3IR_ENHANCE", "H3IR_CREATIVITY")
RUN_ID = re.compile(r"run_\d{8}_\d{6}_\d+")
# What changes the clips, and of those, what also changes which scenes she appears in.
RENDER_ENV = ("AVATAR_SOURCE", "COMFYUI_WORKFLOW", "AVATAR_MIN_SECONDS", "AVATAR_MAX_SECONDS", "H3IR_ENHANCE", "H3IR_CREATIVITY")
SCENE_ENV = ("AVATAR_CLIPS_MIN", "AVATAR_CLIPS_MAX", "AVATAR_MIN_SECONDS", "AVATAR_MAX_SECONDS")


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv[:-1] else default


@dataclass
class RunState(SavedRun):
    """
    What one video's run has finished so far, saved after every step and every
    accepted clip, so a run that was stopped, failed or cut off by a crash can
    continue without paying for that work again. Its working files live in the
    same folder, so runs can't overwrite each other's.

    A clip counts once it passed its checks: a file on disk may be a rejected
    render, or half a download.
    """

    id: str
    argv: list  # main.py's options, without --resume
    env: dict
    number: int  # This video's place in the batch
    videos_after: int  # Videos of the batch still to come after this one
    topic: str = None
    script: list = None
    voiced: bool = False
    video_pairs: list = None
    avatar_indices: list = None
    reference_image: str = None  # Each video picks a persona at random, and has to stay her
    avatar_clips: dict = field(default_factory=dict)
    avatar_prompts: dict = field(default_factory=dict)  # Written per clip, and paid for: a clip rendered again keeps its own
    avatar_done: bool = False
    final: str = None
    provenance: dict = None

    @classmethod
    def new(cls, argv, number, videos_after):
        return cls(id=f"run_{datetime.now():%Y%m%d_%H%M%S}_{number}", argv=list(argv),
                   env={name: os.environ[name] for name in RUN_ENV if os.environ.get(name)},
                   number=number, videos_after=videos_after)

    # Loading (core/saved_run.py): what its checkpoint must hold, and what to mend once loaded.
    RUN_ID = RUN_ID
    SCHEMA = {"argv": list, "env": dict, "number": int, "videos_after": int, "script": list, "avatar_clips": dict,
              "avatar_prompts": dict, "provenance": dict}

    @classmethod
    def runs_dir(cls):
        return RUNS_DIR

    def loaded(self):
        """Its clips and prompts by number again (JSON keeps them as text), and anything whose files have gone marked as still to do."""
        self.avatar_clips = {int(index): path for index, path in self.avatar_clips.items()}
        self.avatar_prompts = {int(index): prompt for index, prompt in self.avatar_prompts.items()}
        self._forget_missing()

    # --- Where its files go ---

    @property
    def audio_dir(self):
        return os.path.join(self.folder, "audio")

    @property
    def clips_dir(self):
        return os.path.join(self.folder, "clips")

    @property
    def temp_dir(self):
        return os.path.join(self.folder, "temp")

    # --- Saving ---

    def keep_clip(self, index, path):
        self.avatar_clips[index] = path
        self.save()

    def keep_prompt(self, index, prompt):
        self.avatar_prompts[index] = prompt
        self.save()

    def adopt(self, argv, env, videos_after):
        """Takes the options chosen now, for Generate to continue this run. Only what they change is done again."""
        changed = lambda names: any(self.env.get(name) != env.get(name) for name in names)
        layout_changed = option(self.argv, "--avatar-clips") != option(argv, "--avatar-clips")
        if option(self.argv, "--voice") != option(argv, "--voice"):
            shutil.rmtree(self.audio_dir, ignore_errors=True)
            self.voiced = False
            self.avatar_clips, self.avatar_done, self.final = {}, False, None  # Lip-synced to the old voice
        if changed(RENDER_ENV) or layout_changed:
            self.avatar_clips, self.avatar_done, self.final = {}, False, None
        if changed(SCENE_ENV) or layout_changed:
            self.avatar_indices, self.avatar_prompts = None, {}
        self.argv, self.env = list(argv), {name: env[name] for name in RUN_ENV if env.get(name)}
        self.number, self.videos_after = 1, videos_after
        self.save()

    def save(self):
        """Save progress or raise an actionable checkpoint error."""
        # Before a topic exists, only a later video of a batch has anything to continue: the videos left.
        if not self.topic and not self.script and self.number == 1:
            return
        workflow = self.env.get("COMFYUI_WORKFLOW") or os.path.join(WORKFLOWS_DIR, "avatar_lipsync.json")
        run_checkpoint.save(self, workflow, {"argv": self.argv, "env": self.env,
                                             "tts_provider": os.getenv("TTS_PROVIDER") or "gemini",
                                             "script_provider": "gemini"})

    def save_manifest(self):
        """Retain provenance after a finished run's working directory is removed."""
        path = os.path.join(RUNS_DIR, "manifests", self.id + ".json")
        run_checkpoint.write(path, {"schema_version": 1, "id": self.id, "provenance": self.provenance})

    def release_batch(self):
        """The batch moved on without this video, so continuing it must not make the rest again."""
        self.videos_after = 0
        if self.topic or self.script:
            self.save()
        else:
            self.remove()

    def remove(self, keep_files=False):
        """State first: without it the run is gone from the list, even if a file refuses to be deleted."""
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"   ⚠️ Could not remove {self.path}: {e}")
        if not keep_files:
            shutil.rmtree(self.folder, ignore_errors=True)

    # --- What is left ---

    def next_stage(self):
        if not self.script:
            return "Topic & script"
        if not self.voiced:
            return "Voice"
        if self.video_pairs is None:
            return "Stock footage"
        if not self.avatar_done:
            return "Avatar clips"
        # Rendering and stitching take seconds, so they are done again rather than tracked scene by scene.
        return "Rendering scenes" if not self.final else "Upload"

    def kept_stages(self):
        return STAGES[:STAGES.index(self.next_stage())]

    def _forget_avatar(self):
        self.avatar_indices, self.reference_image = None, None
        self.avatar_clips, self.avatar_done = {}, False

    def _forget_missing(self):
        if self.voiced and not all(os.path.exists(scene.get("audio_path", "")) for scene in self.script):
            # Her clips are lip-synced to the voice that's gone.
            self.voiced = False
            self.final = None
            self._forget_avatar()
        if self.video_pairs and not all(os.path.exists(path) for pair in self.video_pairs for path in pair or ()):
            self.video_pairs = None
        if self.reference_image and not os.path.exists(self.reference_image):
            self._forget_avatar()
        kept = {index: path for index, path in self.avatar_clips.items() if os.path.exists(path)}
        if len(kept) < len(self.avatar_clips):
            self.avatar_clips, self.avatar_done = kept, False
        if self.final and not os.path.exists(self.final):
            self.final = None


def list_runs():
    """Usable runs, newest first; excluded checkpoints are logged and reported separately."""
    return run_checkpoint.catalogue(RUNS_DIR, RunState.load)


def folder_size(path):
    return sum(os.path.getsize(os.path.join(folder, name))
               for folder, _, names in os.walk(path) for name in names
               if os.path.exists(os.path.join(folder, name)))
