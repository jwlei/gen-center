"""Versioned, atomic run checkpoints and their observed provenance."""
import base64
import copy
import hashlib
import json
import logging
import os
import platform
import time
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from importlib import metadata

from core import gemini_models

SCHEMA_VERSION = 1
SAVE_ATTEMPTS = 5
_catalogue_errors = {}
_catalogue_lock = threading.Lock()
_logger = logging.getLogger(__name__)


class CheckpointError(RuntimeError):
    """A run's checkpoint could not be read or saved."""


def catalogue_errors():
    """Current scan failures for status/reporting; no run content is included."""
    with _catalogue_lock:
        return [dict(error) for errors in _catalogue_errors.values() for error in errors]


def catalogue(folder, loader):
    """List usable runs independently, preserving actionable errors for excluded checkpoints."""
    errors = []
    runs = []
    try:
        names = sorted(os.listdir(folder), reverse=True)
    except FileNotFoundError:
        names = []
    except OSError as error:
        names = []
        errors.append({"path": folder, "error": f"Cannot list checkpoints in {folder}: {error}. Check permissions."})
    for name in names:
        try:
            state = loader(name)
        except CheckpointError as error:
            errors.append({"path": os.path.join(folder, name, "state.json"), "error": str(error)})
            continue
        if state is not None:
            runs.append(state)
    with _catalogue_lock:
        previous = _catalogue_errors.get(folder, [])
        _catalogue_errors[folder] = errors
    for error in errors:
        if error not in previous:
            _logger.warning("Checkpoint excluded from catalogue: %s", error["error"])
    return runs


def load(path, run_id):
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError) as error:
        raise CheckpointError(f"Cannot read checkpoint {path}: {error}. Restore or repair the file.") from error
    if not isinstance(data, dict):
        raise CheckpointError(f"Corrupt checkpoint {path}: expected an object. Restore or repair the file.")
    version = data.pop("schema_version", 0)
    if type(version) is not int or version not in (0, SCHEMA_VERSION):
        raise CheckpointError(f"Unsupported checkpoint schema version {version!r} in {path}; use a compatible app version.")
    if data.get("id") != run_id:
        raise CheckpointError(f"Corrupt checkpoint {path}: run ID does not match its folder.")
    return data


def invalid(path, error):
    return CheckpointError(f"Corrupt checkpoint {path}: {error}. Restore or repair the file.")


def validate(data, path, fields):
    for name, kind in fields.items():
        value = data.get(name)
        if value is not None and not isinstance(value, kind):
            raise invalid(path, f"{name} must be {kind.__name__}")


@lru_cache(maxsize=1)
def package_versions():
    versions = {}
    for name in ("google-genai", "openai", "requests", "ffmpeg-python"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return versions


def provenance(previous, workflow, settings):
    """Record files observed at checkpoint time, not an assertion about earlier renders."""
    manifest = dict(previous or {})
    snapshots = list(manifest.get("workflow_snapshots", []))
    observed = []
    for path in (workflow, os.path.splitext(workflow)[0] + ".map.json" if workflow else None):
        if not path:
            continue
        try:
            with open(path, "rb") as file:
                content = file.read()
        except OSError:
            continue
        digest = hashlib.sha256(content).hexdigest()
        observed.append({"path": path, "sha256": digest})
        if not any(item["path"] == path and item["sha256"] == digest for item in snapshots):
            snapshots.append({"path": path, "sha256": digest, "base64": base64.b64encode(content).decode("ascii")})
    settings = copy.deepcopy(settings)
    settings["gemini_model_candidates"] = {
        "text": gemini_models.get_text_models(), "fast": gemini_models.get_fast_models(),
        "tts": gemini_models.get_tts_models(), "image": gemini_models.get_image_models(),
    }
    settings_history = list(manifest.get("settings_history", []))
    if not settings_history or settings_history[-1].get("settings") != settings or settings_history[-1].get("workflows") != observed:
        settings_history.append({"observed_at": datetime.now(timezone.utc).isoformat(),
                                 "settings": settings, "workflows": observed})
    manifest.update({"observation": "checkpoint time", "workflow_snapshots": snapshots,
                     "settings": settings, "settings_history": settings_history, "python_version": platform.python_version(),
                     "app_version": None, "package_versions": package_versions()})
    return manifest


def write(path, data):
    temp = path + "." + uuid.uuid4().hex + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=1)
        for attempt in range(SAVE_ATTEMPTS):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == SAVE_ATTEMPTS - 1:
                    raise
                time.sleep(0.2)
    except (OSError, TypeError, ValueError) as error:
        raise CheckpointError(f"Could not save checkpoint {path}: {error}. Check disk space and permissions before continuing.") from error
    finally:
        try:
            os.remove(temp)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def save(state, workflow, settings):
    try:
        state.provenance = provenance(state.provenance, workflow, settings)
        data = asdict(state)
        data["schema_version"] = SCHEMA_VERSION
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise CheckpointError(f"Could not prepare checkpoint {state.path}: {error}. Check the run settings.") from error
    write(state.path, data)
