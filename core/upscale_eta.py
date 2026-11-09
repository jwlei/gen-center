"""
How long an upscale on its own takes: an image of a set made bigger (pipelines/image/upscale.py), or a film made bigger
with RTX VSR (pipelines/video/upscale.py). Each way is timed apart, per megapixel it makes (and per second of film),
in the side's own timings file under "Upscale | <method>", so the first one learns its real time and the next is right.

The job prints no stages, so this is one step from start to end: what it should take, less what has gone by.
"""
import os
import re
import time

from core.eta_keys import SEPARATOR, Timings

# Seconds per megapixel made, until timed: as measured on this 12 GB card for an image ending around 4 MP.
IMAGE_RATES = {"fast": 4, "ultrasharp": 5, "usdu": 30, "seedvr2": 45}
# Seconds per second of film, per megapixel made, for RTX VSR.
FILM_RATE = 3.0
# Loading the models and the image in and out, whatever the size.
START_SECONDS = {"fast": 8, "ultrasharp": 8, "usdu": 25, "seedvr2": 40, "vsr": 20}
FAST_MOST_EDGE, SEEDVR2_MOST_EDGE = 8192, 2560
SMALL_DRIFT_SECONDS = 30


def _option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv[:-1] else default


def is_upscale(argv):
    return "pipelines.image.upscale" in (argv or []) or "pipelines.video.upscale" in (argv or [])


def image_target(width, height, method, resolution=0):
    """The size an image upscale makes, as pipelines/image/upscale.py works it out."""
    if method == "seedvr2":
        shorter = resolution or min(SEEDVR2_MOST_EDGE, 2 * min(width, height))
        scale = shorter / min(width, height)
    else:
        scale = min(2, FAST_MOST_EDGE / max(width, height))
    return round(width * scale), round(height * scale)


class UpscaleEta:
    """The ETA a running upscale job reports, and the estimate a queued one shows."""

    def __init__(self, argv, path):
        self.timings = Timings(path, {})
        self.film = "pipelines.video.upscale" in argv
        self.method = "vsr" if self.film else _option(argv, "--method", "seedvr2")
        self.amount = self._amount(argv)
        self.started = time.time()
        self.original_total = round(self.seconds())

    def _amount(self, argv):
        """What the time scales with: megapixels made (an image), or megapixel-seconds made (a film). None if unknown."""
        try:
            if self.film:
                from pipelines.video import paths
                from pipelines.video.upscale import probe
                size = probe(os.path.join(paths.OUTPUT_DIR, _option(argv, "--film", "")))
                if not size:
                    return None
                scale = float(_option(argv, "--scale", 2))
                width, height, seconds = size
                return width * scale * height * scale / 1e6 * seconds
            from PIL import Image
            from panel.image import upscale_position
            from pipelines.image.run_state import RunState
            state = RunState.load(_option(argv, "--resume"))
            position = upscale_position(state, argv) if state else None
            if not position or not position.isdigit() or not 1 <= int(position) <= len(state.shots):
                return None
            with Image.open(state.image_path(state.shots[int(position) - 1])) as image:
                made = image_target(*image.size, self.method, int(_option(argv, "--resolution", 0) or 0))
            return made[0] * made[1] / 1e6
        except (OSError, ValueError, TypeError, AttributeError, ImportError):
            return None

    def _keys(self):
        """Per megapixel made: per method, then upscales at all."""
        unit = "per MP-second" if self.film else "per MP"
        return [SEPARATOR.join(("Upscale", self.method, unit)), SEPARATOR.join(("Upscale", unit))]

    def _start_keys(self):
        return [SEPARATOR.join(("Upscale", self.method, "start"))]

    def seconds(self):
        start = self.timings.step(self._start_keys(), START_SECONDS.get(self.method, 15))
        rate = self.timings.step(self._keys(), FILM_RATE if self.film else IMAGE_RATES.get(self.method, 30))
        return start + rate * (self.amount if self.amount is not None else (8 if self.film else 4))

    def plan(self):
        total = round(self.seconds())
        return {"steps": [{"name": "Upscale", "seconds": total}], "total": total}

    def finish(self):
        """It succeeded: what it took, less the fixed start, per megapixel it made."""
        if self.amount:
            start = self.timings.step(self._start_keys(), START_SECONDS.get(self.method, 15))
            spent = time.time() - self.started
            self.timings.learn_step(self._keys(), max(0.0, spent - start) / self.amount)
            self.timings.save()

    def estimate(self):
        elapsed = time.time() - self.started
        left = max(self.seconds() - elapsed, 0)
        adjusted = elapsed + left
        changes = []
        drift = adjusted - self.original_total
        if abs(drift) >= SMALL_DRIFT_SECONDS:
            changes.append({"text": f"Running {'slower' if drift > 0 else 'faster'} than estimated", "seconds": round(drift)})
        return {"steps": [{"state": "now", "seconds": round(left)}], "total_left": round(left), "original_total": self.original_total,
                "original_left": round(self.original_total - elapsed), "adjusted_total": round(adjusted), "changes": changes}

    def __getattr__(self, name):
        """What the job reports for other runs (stages, clips, images): an upscale has none of them."""
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: None
