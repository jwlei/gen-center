"""Wait for ComfyUI's worker to finish unloading models and clearing its caches."""
import math
import time

import requests

# What an emptied ComfyUI still keeps: PyTorch's caching allocator holds a block or two (measured: 256 KB allocated,
# 32 MB reserved of 12 GB), which is not a model left behind. Anything that size is; a model is gigabytes.
LEFTOVER_BYTES = 512 * 2**20
# How long a ComfyUI still busy is waited for: a run stopped or paused mid-image leaves its prompt ending for a few
# seconds once interrupted, and ComfyUI refuses to clean up (409) until it has.
BUSY_WAIT = 60


def release(url, busy_wait=None):
    deadline = time.monotonic() + (BUSY_WAIT if busy_wait is None else busy_wait)
    try:
        while True:
            response = requests.post(f"{url.rstrip('/')}/gen-center/free", json={}, timeout=125)
            if response.status_code != 409 or time.monotonic() >= deadline:
                break
            time.sleep(1)  # Still finishing what it was doing: asked again in a moment
        if response.status_code == 409:
            raise RuntimeError(f"ComfyUI was still busy after {BUSY_WAIT if busy_wait is None else busy_wait} s, so it couldn't clean up.")
        if response.status_code == 404:
            raise RuntimeError("Install the gen-center cleanup integration and restart ComfyUI "
                               "(python scripts/install_comfy_cleanup.py).")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("version") != 1 or body.get("completed") is not True:
            raise RuntimeError("ComfyUI did not acknowledge completed cleanup.")
        devices = body.get("devices")
        if not isinstance(devices, list) or not devices:
            raise RuntimeError("ComfyUI returned no memory measurements after cleanup.")
        for device in devices:
            if not isinstance(device, dict) or device.get("type") not in ("cpu", "cuda"):
                raise RuntimeError("ComfyUI returned an unsupported or invalid memory device.")
            for field in ("vram_total", "vram_free", "torch_allocated", "torch_reserved"):
                value = device.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise RuntimeError(f"ComfyUI returned an invalid {field} measurement.")
            if device["vram_total"] <= 0 or device["vram_free"] > device["vram_total"]:
                raise RuntimeError("ComfyUI returned invalid available memory.")
            if device["type"] == "cuda" and max(device["torch_allocated"], device["torch_reserved"]) > LEFTOVER_BYTES:
                held = max(device["torch_allocated"], device["torch_reserved"]) / 2**20
                raise RuntimeError(f"ComfyUI still holds {held:.0f} MB of GPU memory after cleanup.")
        return devices
    except (requests.RequestException, ValueError, OverflowError) as error:
        raise RuntimeError(f"Could not verify ComfyUI memory cleanup: {error}") from error
