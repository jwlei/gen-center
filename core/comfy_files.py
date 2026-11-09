"""
What this app leaves in ComfyUI's own folders, cleaned up: nothing it makes should stay there.

    input/   what it uploads for a job (autocomfyui_..., autogen_..., the Shorts avatar's): each job uploads its own
             again, so they go once a job ends.
    output/  a result fetched from there (most go to ComfyUI's temp folder instead) goes once it is downloaded
             (forget_output). H3 Infinite keeps a run's clips in autogen_h3_infinite/<run>, which it continues and
             redoes from: they go with the run (forget_h3_run), or once the run is gone. H3's motion memory
             (minimax_motion_context_cache) goes once nothing is running or waiting.
ComfyUI's folder is found as core/lora_check.py finds it (COMFYUI_DIR, else beside COMFYUI_LAUNCHER). Without it,
nothing is done.
"""
import os
import shutil

from core.lora_check import comfyui_folders

INPUT_PREFIXES = ("autocomfyui_", "autogen_", "pipeline_no_image", "aishorts_avatar_")
H3_INFINITE = "autogen_h3_infinite"
CACHES = ("minimax_motion_context_cache",)


def comfyui_dir():
    folders = comfyui_folders()
    return folders[0] if folders else None


def _inside(root, path):
    root, path = os.path.abspath(root), os.path.abspath(path)
    return os.path.commonpath([root, path]) == root and path != root


def _remove(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False  # In use (ComfyUI still has it open): the next clean-up takes it


def clean_inputs():
    """Removes what this app uploaded to ComfyUI's input folder. Returns how many went."""
    root = comfyui_dir()
    folder = os.path.join(root, "input") if root else None
    if not folder or not os.path.isdir(folder):
        return 0
    return sum(_remove(os.path.join(folder, name)) for name in os.listdir(folder)
               if name.startswith(INPUT_PREFIXES) and os.path.isfile(os.path.join(folder, name)))


def forget_output(filename, subfolder="", kind="output"):
    """A result just downloaded from ComfyUI's output folder: its copy there goes. Anything else is left alone."""
    root = comfyui_dir()
    if kind != "output" or not root or not filename:
        return False
    output = os.path.join(root, "output")
    path = os.path.join(output, subfolder or "", filename)
    return _inside(output, path) and _remove(path)


def forget_h3_run(run_id):
    """H3 Infinite's clips of a run, which goes."""
    root = comfyui_dir()
    if not root or not run_id:
        return False
    output = os.path.join(root, "output", H3_INFINITE)
    path = os.path.join(output, str(run_id))
    return _inside(output, path) and _remove(path)


def clean_idle(existing_runs):
    """
    Once nothing is running or waiting: H3's motion memory, and H3 Infinite's clips of runs no longer saved.
    existing_runs: the ids of the video runs still saved. Returns how many went.
    """
    root = comfyui_dir()
    if not root:
        return 0
    output = os.path.join(root, "output")
    gone = sum(_remove(os.path.join(output, cache)) for cache in CACHES if os.path.exists(os.path.join(output, cache)))
    runs = os.path.join(output, H3_INFINITE)
    if os.path.isdir(runs):
        gone += sum(_remove(os.path.join(runs, name)) for name in os.listdir(runs) if name not in existing_runs)
    return gone
