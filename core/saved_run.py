"""
What every pipeline's saved run shares (pipelines/<side>/run_state.py): how it's loaded from its checkpoint, where its
folder is, and saving a change. Each side's RunState is a dataclass that also derives from SavedRun, and says:

    RUN_ID      the pattern its run ids follow
    SCHEMA      the types of the fields its checkpoint must have (core/run_checkpoint.py validate)
    runs_dir()  the folder its runs are kept in, asked each time so a test or a move can change it
    loaded()    what to mend after loading: files that have gone marked as still to do, keys made numbers again
    save()      its own, as each keeps different settings with its checkpoint
"""
import os

from core import run_checkpoint


class SavedRun:
    RUN_ID = None
    SCHEMA = {}

    @classmethod
    def runs_dir(cls):
        raise NotImplementedError

    @classmethod
    def load(cls, run_id):
        """The saved run, mended (loaded()). None if there isn't one; raises run_checkpoint's error for a broken one."""
        if not cls.RUN_ID.fullmatch(str(run_id)):
            return None
        path = os.path.join(cls.runs_dir(), run_id, "state.json")
        saved = run_checkpoint.load(path, run_id)
        if saved is None:
            return None
        run_checkpoint.validate(saved, path, cls.SCHEMA)
        try:
            state = cls(**{name: value for name, value in saved.items() if name in cls.__dataclass_fields__})
            state.loaded()
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise run_checkpoint.invalid(path, error) from error
        return state

    def loaded(self):
        """What to mend once loaded. Nothing, unless a side says."""

    @property
    def folder(self):
        return os.path.join(self.runs_dir(), self.id)

    @property
    def path(self):
        return os.path.join(self.folder, "state.json")

    def update(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)
        self.save()
