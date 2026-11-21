"""
What every pipeline's run ETA shares (pipelines/<side>/run_eta.py, the Status panel's estimate): reading an option from
the run's command line, the step list it shows, and the changes that explain why the estimate moved. Each side's RunEta
derives from StagedEta and keeps what is its own: how long each of its stages takes, learned per model and size.

A RunEta has: number, total, name (the stage it's on), started and stage_started (times), finished ({stage number:
seconds}), original_total (the first estimate), changes ([{text, seconds}]), and _current_left(now).
"""
import time

# Drift the noted changes don't explain, past which it says the run is going slower or faster than estimated.
SMALL_DRIFT_SECONDS = 60


def option(argv, name, default=None):
    """The value after name on the run's command line, or default."""
    return argv[argv.index(name) + 1] if name in argv[:-1] else default


class StagedEta:
    def stage(self, number, total, name):
        """A stage starting: the one before it is timed and learned (_finish_stage)."""
        if self.number and number == self.number + 1:
            self._finish_stage()
        self.number, self.total, self.name = number, total, name
        self.stage_started = time.time()
        self.local_mark = self.local.spent

    def _note(self, text, seconds):
        self.changes.append({"text": text, "seconds": round(seconds)})

    def _all_changes(self, adjusted):
        """The noted changes, plus whatever they don't explain, so they add up to the adjusted ETA."""
        changes = list(self.changes)
        drift = adjusted - self.original_total - sum(change["seconds"] for change in changes)
        if abs(drift) >= SMALL_DRIFT_SECONDS:
            pace = "slower" if drift > 0 else "faster"
            changes.append({"text": f"Running {pace} than estimated", "seconds": round(drift)})
        return changes

    def _steps(self, names, now, kept, upcoming):
        """
        Each stage as Status shows it ({state, seconds}: kept, done, now or next), and the seconds left in this run.
        kept(name): whether a stage was kept from before; upcoming(name): how long a stage still to come takes.
        """
        steps, left = [], 0
        for number, name in enumerate(names, 1):
            if kept(name):
                steps.append({"state": "kept", "seconds": 0})
            elif number < self.number:
                steps.append({"state": "done", "seconds": round(self.finished.get(number, 0))})
            elif number == self.number:
                current = self._current_left(now)
                left += current
                steps.append({"state": "now", "seconds": round(current)})
            else:
                seconds = upcoming(name)
                left += seconds
                steps.append({"state": "next", "seconds": round(seconds)})
        return steps, left

    def _summary(self, steps, left, now):
        """What estimate() returns: the steps, the seconds left, and how that compares with the first estimate."""
        elapsed = now - self.started
        adjusted = elapsed + left
        return {"steps": steps, "total_left": round(left), "original_total": self.original_total,
                "original_left": round(self.original_total - elapsed), "adjusted_total": round(adjusted),
                "changes": self._all_changes(adjusted)}
