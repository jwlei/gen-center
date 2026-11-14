"""Compare local model offload settings while the panel and ComfyUI are idle."""
import json
import os
import re
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests
from dotenv import load_dotenv
from gguf import GGUFReader

load_dotenv(os.path.join(ROOT, ".env"))

from core import h3_refiner
from core.paths import LOGS_DIR
from panel import settings


PANEL = "http://127.0.0.1:8800"
COMFY = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
PROMPT = ("Describe a quiet coastal village at sunrise, including the buildings, weather, "
          "people, sounds and small details. Write several detailed paragraphs.")


class BenchmarkInterrupted(RuntimeError):
    pass


def connection_refused(error):
    while error is not None:
        if isinstance(error, ConnectionRefusedError):
            return True
        error = error.__cause__ or error.__context__
    return False


def check_idle(session):
    response = session.get(PANEL + "/api/status?catalogue_revision=0", timeout=10)
    response.raise_for_status()
    status = response.json()
    queues = (status["queue"], status["upload"]["queue"])
    if (status["running"] or status["prompt_writer"]["running"] or status["upload"]["running"]
            or any(queue["current"] or (not queue["held"] and any(not item.get("later") for item in queue["items"]))
                   for queue in queues)):
        raise RuntimeError("Panel work is running or ready to start.")
    try:
        response = session.get(COMFY + "/queue", timeout=5)
        response.raise_for_status()
        queue = response.json()
        if not isinstance(queue.get("queue_running"), list) or not isinstance(queue.get("queue_pending"), list):
            raise RuntimeError("ComfyUI returned an invalid queue.")
        if queue["queue_running"] or queue["queue_pending"]:
            raise RuntimeError("ComfyUI has work running or queued.")
    except requests.ConnectionError as error:
        if not connection_refused(error):
            raise


def monitor(session, stop, interrupted, refiner):
    while not stop.wait(1):
        try:
            check_idle(session)
        except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as error:
            interrupted.append(str(error))
            if refiner.process and refiner.process.poll() is None:
                refiner.process.terminate()
            return


def measure(session, model_id, layers):
    check_idle(session)
    refiner = h3_refiner.Refiner(comfy_url=COMFY, require_compiler=False, model_id=model_id,
                                 gpu_layers=layers, verbose=True)
    interrupted, stop = [], threading.Event()
    watch_session = requests.Session()
    watch_session.cookies.update(session.cookies)
    watcher = threading.Thread(target=monitor, args=(watch_session, stop, interrupted, refiner), daemon=True)
    watcher.start()
    try:
        with refiner:
            if interrupted:
                raise RuntimeError(interrupted[0])
            refiner.log.flush()
            with open(refiner.log.name, encoding="utf-8", errors="replace") as source:
                log = source.read()
            match = re.search(r"offloaded (\d+)/(\d+) layers to GPU", log)
            if layers != 0 and not match:
                raise RuntimeError("The runner did not report how many layers were offloaded.")
            actual = (int(match.group(1)), int(match.group(2))) if match else (0, None)
            if layers == "all" and actual[0] != actual[1]:
                raise RuntimeError(f"Full offload requested but only {actual[0]}/{actual[1]} layers were offloaded.")
            if isinstance(layers, int) and layers > 0 and not (0 < actual[0] < actual[1]):
                raise RuntimeError(f"Partial offload requested but runner reported {actual[0]}/{actual[1]} layers.")
            if layers == 0 and actual[0] != 0:
                raise RuntimeError(f"CPU-only requested but runner offloaded {actual[0]} layers.")
            total_tokens = total_ms = 0
            for iteration in range(3):
                response = requests.post(refiner.url + "/chat/completions", json={
                    "model": "h3-refiner",
                    "messages": [{"role": "user", "content": PROMPT}],
                    "temperature": 0,
                    "max_tokens": 128,
                    "cache_prompt": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }, timeout=900)
                response.raise_for_status()
                body = response.json()
                timing = body["timings"]
                tokens, milliseconds = timing["predicted_n"], timing["predicted_ms"]
                if not isinstance(tokens, (int, float)) or not isinstance(milliseconds, (int, float)) \
                        or tokens < 32 or milliseconds <= 0:
                    raise RuntimeError("The runner returned insufficient or invalid token timings.")
                if iteration:
                    total_tokens += tokens
                    total_ms += milliseconds
            if interrupted:
                raise RuntimeError(interrupted[0])
            check_idle(session)
            return {"gpu_layers": layers, "offloaded": actual[0], "total_layers": actual[1],
                    "tokens": total_tokens, "milliseconds": total_ms}
    finally:
        stop.set()
        watcher.join()
        watch_session.close()
        if interrupted:
            raise BenchmarkInterrupted("Benchmark interrupted: " + interrupted[0])


def main():
    session = requests.Session()
    password = os.getenv("APP_PASSWORD")
    if password:
        response = session.post(PANEL + "/login", data={"password": password}, timeout=10)
        response.raise_for_status()
    check_idle(session)
    results = {}
    for model in settings.local_models():
        model_id = model["id"]
        _, _, server, path, _ = h3_refiner._paths(model_id, require_compiler=False)
        model_mtime, server_mtime = os.path.getmtime(path), os.path.getmtime(server)
        metadata = GGUFReader(path)
        architecture = metadata.fields["general.architecture"].contents()
        blocks = metadata.fields[architecture + ".block_count"].contents()
        del metadata
        candidates, failures = [], []
        for layers in ("all", blocks // 2, 0):
            print(f"\nBenchmarking {model_id}: gpu-layers={layers}", flush=True)
            try:
                candidate = measure(session, model_id, layers)
                candidates.append(candidate)
                print(f"  {candidate['tokens'] * 1000 / candidate['milliseconds']:.1f} tok/s; "
                      f"offloaded {candidate['offloaded']}/{candidate['total_layers']} layers", flush=True)
            except BenchmarkInterrupted:
                raise
            except (requests.RequestException, RuntimeError, ValueError, OSError, KeyError) as error:
                check_idle(session)
                failures.append({"gpu_layers": layers, "error": str(error)})
                print(f"  Failed: {error}", flush=True)
        if os.path.getmtime(path) != model_mtime or os.path.getmtime(server) != server_mtime:
            raise RuntimeError(f"Model or runner changed during benchmark for {model_id}; previous results remain unchanged.")
        if not candidates:
            raise RuntimeError(f"No successful benchmark for {model_id}; previous results remain unchanged.")
        best = max(candidates, key=lambda result: result["tokens"] / result["milliseconds"])
        results[model_id] = {**best, "model_path": os.path.normcase(os.path.abspath(path)),
                             "model_mtime": model_mtime,
                             "server_path": os.path.normcase(os.path.abspath(server)),
                             "server_mtime": server_mtime, "candidates": candidates, "failures": failures}
    check_idle(session)
    os.makedirs(LOGS_DIR, exist_ok=True)
    path = os.path.join(LOGS_DIR, "local_model_benchmarks.json")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=LOGS_DIR, delete=False) as target:
            temporary = target.name
            json.dump({"at": time.time(), "models": results}, target, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    print("\nBenchmark results saved; previous speed samples are excluded.", flush=True)


if __name__ == "__main__":
    main()
