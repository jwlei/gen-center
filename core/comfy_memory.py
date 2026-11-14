"""Wait for ComfyUI's worker to finish unloading models and clearing its caches."""
import math

import requests


def release(url):
    try:
        response = requests.post(f"{url.rstrip('/')}/gen-center/free", json={}, timeout=125)
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
            if device["type"] == "cuda" and (device["torch_allocated"] or device["torch_reserved"]):
                raise RuntimeError("ComfyUI still holds GPU tensors or cached GPU allocations after cleanup.")
        return devices
    except (requests.RequestException, ValueError, OverflowError) as error:
        raise RuntimeError(f"Could not verify ComfyUI memory cleanup: {error}") from error
