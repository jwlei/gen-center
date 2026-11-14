"""Acknowledged cleanup on ComfyUI's prompt worker, not its HTTP thread."""
import asyncio
import functools
import gc
import logging
import threading

from aiohttp import web
import comfy.model_management as memory
import execution
from server import PromptServer

NODE_CLASS_MAPPINGS = {}
_worker = threading.local()
_pending = None


class Cleanup:
    def __init__(self):
        self.done = threading.Event()
        self.devices = None
        self.error = None

    def __bool__(self):
        # ComfyUI tests this flag immediately before resetting the executor's caches.
        _worker.cleanup = self
        return True


def measurements():
    if memory.current_loaded_models:
        raise RuntimeError("ComfyUI still has loaded models after unloading.")
    devices = []
    for device in memory.get_all_torch_devices():
        if device.type not in ("cpu", "cuda"):
            raise RuntimeError(f"Verified cleanup does not support the {device.type} backend.")
        total = memory.get_total_memory(device)
        free = memory.get_free_memory(device)
        allocated = memory.torch.cuda.memory_allocated(device) if device.type == "cuda" else 0
        reserved = memory.torch.cuda.memory_reserved(device) if device.type == "cuda" else 0
        devices.append({"type": device.type, "index": device.index, "vram_total": total,
                        "vram_free": free, "torch_allocated": allocated, "torch_reserved": reserved})
    return devices


_reset = execution.PromptExecutor.reset


@functools.wraps(_reset)
def reset(self):
    cleanup = getattr(_worker, "cleanup", None)
    if cleanup is None:
        return _reset(self)
    try:
        _reset(self)
        gc.collect()
        cuda_devices = [device for device in memory.get_all_torch_devices() if device.type == "cuda"]
        for device in cuda_devices:
            memory.torch.cuda.synchronize(device)
        if cuda_devices:
            # cuBLAS workspaces survive executor reset and empty_cache.
            memory.torch._C._cuda_clearCublasWorkspaces()
        memory.soft_empty_cache()
        cleanup.devices = measurements()
    except Exception as error:
        cleanup.error = str(error)
        logging.exception("gen-center: verified ComfyUI cleanup failed")
        raise
    finally:
        del _worker.cleanup
        cleanup.done.set()


execution.PromptExecutor.reset = reset


@PromptServer.instance.routes.post("/gen-center/free")
async def free(request):
    global _pending
    queue = PromptServer.instance.prompt_queue
    with queue.mutex:
        if queue.get_tasks_remaining():
            return web.json_response({"error": "ComfyUI has work running or queued."}, status=409)
        if _pending is None or _pending.done.is_set():
            _pending = Cleanup()
            queue.set_flag("unload_models", True)
            queue.set_flag("free_memory", _pending)
        cleanup = _pending
    if not await asyncio.to_thread(cleanup.done.wait, 120):
        return web.json_response({"error": "Timed out waiting for ComfyUI's worker to finish cleanup."}, status=504)
    if cleanup.error:
        return web.json_response({"error": cleanup.error}, status=500)
    with queue.mutex:
        if queue.get_tasks_remaining():
            return web.json_response({"error": "ComfyUI received work during cleanup."}, status=409)
    return web.json_response({"version": 1, "completed": True, "devices": cleanup.devices})
