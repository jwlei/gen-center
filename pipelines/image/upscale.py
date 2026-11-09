"""
Makes one image of a set bigger, as a new image in the set beside the one it came from: sharper with SeedVR2, in
minutes, or in seconds with Superscale-SP (--method fast), which adds no new content.

    python -m pipelines.image.upscale --resume image_20261104_120000 --image 3

The settings are those the Krea 2 SFW/NSFW workflow runs SeedVR2 with on this 12 GB card: the 7B model, swapping
36 blocks to the CPU, tiled VAE. Attention is sdpa, as everywhere here (sageattn isn't installed).
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from core.paths import comfyui_client_id
from core.saved_workflows import unique_name
from pipelines.image.comfy import IMAGE_EXTENSIONS
from pipelines.image.run_state import RunState
from pipelines.video.comfy import DEFAULT_COMFYUI_URL, DEFAULT_TIMEOUT, ComfyClient

# Twice the shorter side, up to what the card holds at once with its tiled VAE.
FACTOR = 2
MOST_EDGE = 2560
DIT_MODEL = "seedvr2_ema_7b_fp16.safetensors"
VAE_MODEL = "ema_vae_fp16.safetensors"
SUFFIX = "_upscaled"


class UpscaleClient(ComfyClient):
    """ComfyClient's queueing, waiting and downloading, for a workflow made here rather than one saved in ComfyUI."""

    def __init__(self):
        self.url = (os.getenv("COMFYUI_URL") or DEFAULT_COMFYUI_URL).rstrip("/")
        self.timeout = int(os.getenv("COMFYUI_TIMEOUT") or DEFAULT_TIMEOUT)
        self.client_id = comfyui_client_id()


def upscale_workflow(image, resolution, denoise=0.0):
    """
    SeedVR2 on one image, its shorter side to resolution, into ComfyUI's temp folder (PreviewImage), not its output.
    denoise: SeedVR2's latent noise (latent_noise_scale), 0-1: it has no denoise of its own (one step restores the
    picture), and the noise it adds during that step is what makes it draw more, and soften what it would overdo.
    """
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "SeedVR2LoadDiTModel", "inputs": {
            "model": DIT_MODEL, "device": "cuda:0", "blocks_to_swap": 36, "swap_io_components": False,
            "offload_device": "cpu", "cache_model": False, "attention_mode": "sageattn_2"}},
        "3": {"class_type": "SeedVR2LoadVAEModel", "inputs": {
            "model": VAE_MODEL, "device": "cuda:0", "encode_tiled": True, "encode_tile_size": 1024, "encode_tile_overlap": 128,
            "decode_tiled": True, "decode_tile_size": 1024, "decode_tile_overlap": 128, "tile_debug": "false",
            "offload_device": "cpu", "cache_model": False}},
        "4": {"class_type": "SeedVR2VideoUpscaler", "inputs": {
            "image": ["1", 0], "dit": ["2", 0], "vae": ["3", 0], "seed": 777, "resolution": resolution, "max_resolution": 0,
            "batch_size": 1, "uniform_batch_size": False, "color_correction": "lab", "temporal_overlap": 0, "prepend_frames": 0,
            "input_noise_scale": 0.0, "latent_noise_scale": float(denoise or 0), "offload_device": "cpu", "enable_debug": False}},
        "5": {"class_type": "PreviewImage", "inputs": {"images": ["4", 0]}},
    }
    # Titled as ComfyUI's own exports are, so its queue and history say what each node is.
    for node in workflow.values():
        node["_meta"] = {"title": node["class_type"]}
    return workflow


# The fast way, in seconds: the Superscale-SP model (ESRGAN, 4x) Kokon settled on, then down to the size wanted. Strength
# mixes it with a plain resize, to tone down texture the model invents (Kokon's upscaler strength).
FAST_MODEL = "4x_NMKD-Superscale-SP_178000_G.pth"
FAST_MOST_EDGE = 8192
# The ways that only run an upscale model (ESRGAN, 4x), then down to twice the size: {method: (model, name)}.
# 4x-UltraSharp keeps the picture as it is, just bigger and with crisper edges ("Method 1", the AI model upscale).
MODEL_METHODS = {"fast": (FAST_MODEL, "Superscale-SP"), "ultrasharp": ("4x-UltraSharp.pth", "4x-UltraSharp")}
# The ways that draw it again with the set's own model and prompt (pipelines/image/refine_upscale.py).
REFINE_METHODS = {"usdu": "Ultimate SD Upscale"}
# A workflow's options that have an LLM write the prompt (core/workflow_options.py _role): off for a refining upscale.
LLM_ROLES = ("prompt_enhancer", "image_to_prompt")
METHODS = ("seedvr2", *MODEL_METHODS, *REFINE_METHODS)


def fast_workflow(image, model=FAST_MODEL):
    """An upscale model (Superscale-SP unless said) on one image, 4x, into ComfyUI's temp folder (PreviewImage)."""
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "PreviewImage", "inputs": {"images": ["3", 0]}},
    }
    for node in workflow.values():
        node["_meta"] = {"title": node["class_type"]}
    return workflow


def fast_size(width, height):
    """Twice the size, its longer side held to what an image here can be."""
    scale = min(FACTOR, FAST_MOST_EDGE / max(width, height))
    return round(width * scale), round(height * scale)


def blended(made, source, size, strength):
    """The model's image at size, mixed with the source plainly resized: strength 1 is the model's alone."""
    from PIL import Image
    sharp = made.convert("RGB").resize(size, Image.LANCZOS)
    if strength >= 1:
        return sharp
    plain = source.convert("RGB").resize(size, Image.LANCZOS)
    return Image.blend(plain, sharp, max(0.0, strength))


def target_resolution(width, height):
    """The shorter side it's made at: twice what it is, held to what fits."""
    return min(MOST_EDGE, FACTOR * min(width, height))


def refined(state, shot, uploaded, method, denoise, save_as):
    """Ultimate SD Upscale: the set's own workflow, filled in as for this image, with the upscale spliced in."""
    from pipelines.image import refine_upscale
    from pipelines.image.comfy import ImageClient
    from pipelines.image.main import upload_images
    if not state.workflow:
        raise RuntimeError("This set has no saved workflow to draw it again with.")
    os.environ["COMFYUI_WORKFLOW"] = state.workflow
    # Its own prompt for the tiles: a prompt enhancer or image-to-prompt would write another, on a new seed.
    options = {**(state.options or {}), **{role: "0" for role in LLM_ROLES if role in (state.options or {})}}
    client = ImageClient(options)
    images = upload_images(state, client) if not state.region else []
    graph = client.filled(shot["prompt"], images, *client.render_size(state.width, state.height))
    try:
        graph = refine_upscale.SPLICES[method](graph, uploaded, denoise=denoise)
    except refine_upscale.Unsupported as e:
        raise RuntimeError(f"{REFINE_METHODS[method]} can't run on this set's workflow: {e}")
    entry = client._run(graph, shot.get("used_seed", shot.get("seed")))
    return client._download(entry, save_as, IMAGE_EXTENSIONS, "an image")


def keep_origin(source, path, used):
    """
    The upscaled PNG keeps what the original's says made it (ComfyUI's "prompt" and "workflow", and with them its
    seed), not the upscale's graph, whose seed is the upscaler's own (777) or, re-saved after a blend, none at all.
    What upscaled it goes beside them. Kept as it was if the original's can't be read.
    """
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    try:
        with Image.open(source) as original:
            texts = {key: value for key, value in original.info.items() if isinstance(value, str)}
        if not texts:
            return
        info = PngInfo()
        for key, value in texts.items():
            info.add_text(key, value)
        info.add_text("upscaled_with", used)
        part = path + ".part"
        with Image.open(path) as made:
            made.save(part, format="PNG", pnginfo=info)
        os.replace(part, path)
    except OSError as e:
        print(f"   ⚠️ Could not keep the original's seed and workflow in the upscaled image: {e}")


def upscale(state, position, comfy, method="seedvr2", strength=1.0, resolution=0, denoise=None):
    """Makes the image at position again, bigger, and puts it in the set after it. Returns the new file's path."""
    from PIL import Image
    shot = state.shots[position - 1]
    source = state.image_path(shot)
    with Image.open(source) as image:
        width, height = image.size
    uploaded = comfy.upload(source, f"autocomfyui_{state.id}_upscale_{position}.png")
    stem = unique_name(state.output_dir, os.path.splitext(shot["file"])[0] + SUFFIX, ".png")
    if method in REFINE_METHODS:
        from pipelines.image.refine_upscale import DENOISE
        denoise = DENOISE[method] if denoise is None else denoise
        print(f"🔍 Upscaling image {position}, {width}x{height}, to twice the size with {REFINE_METHODS[method]}, denoise {denoise:g}...")
        path = refined(state, shot, uploaded, method, denoise, os.path.join(state.output_dir, stem))
    elif method in MODEL_METHODS:
        model, name = MODEL_METHODS[method]
        size = fast_size(width, height)
        print(f"🔍 Upscaling image {position}, {width}x{height}, to {size[0]}x{size[1]} with {name}, strength {strength:g}...")
        entry = comfy._run(fast_workflow(uploaded, model), 777)
        path = comfy._download(entry, os.path.join(state.output_dir, stem), IMAGE_EXTENSIONS, "an image")
        with Image.open(path) as made, Image.open(source) as original:
            finished = blended(made, original, size, strength)
        part = path + ".part"
        finished.save(part, format="PNG")
        os.replace(part, path)
    else:
        resolution = resolution or target_resolution(width, height)
        print(f"🔍 Upscaling image {position}, {width}x{height}, to {resolution} on its shorter side"
              f"{f', denoise {denoise:g}' if denoise else ''}...")
        entry = comfy._run(upscale_workflow(uploaded, resolution, denoise or 0), 777)
        path = comfy._download(entry, os.path.join(state.output_dir, stem), IMAGE_EXTENSIONS, "an image")
    how = {"seedvr2": "upscaled", "fast": "upscaled fast", "ultrasharp": "upscaled with UltraSharp",
           "usdu": "upscaled with Ultimate SD"}[method]
    # What made it bigger, for the gallery's "Upscaled:" line.
    used = {"seedvr2": ", ".join(["SeedVR2", *([f"{resolution}p"] if resolution else []), *([f"denoise {denoise:g}"] if denoise else [])]),
            "fast": f"Superscale-SP, strength {strength:g}", "ultrasharp": f"4x-UltraSharp, strength {strength:g}",
            "usdu": f"Ultimate SD, denoise {denoise:g}" if denoise is not None else "Ultimate SD"}[method]
    keep_origin(source, path, used)
    # Its own copy of what made the original: independent of it from here on.
    made = {**{key: value for key, value in shot.items() if key not in ("redo",)}, "setup": state.shot_setup(shot),
            "title": f"{shot['title']} · {how}", "file": os.path.basename(path), "upscaled_from": position, "upscaled_with": used}
    state.shots.insert(position, made)
    state.save()
    with Image.open(path) as image:
        print(f"✅ Upscaled to {image.size[0]}x{image.size[1]}: {path}")
    return path


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--resume", metavar="RUN", required=True, help="The set the image is in.")
    parser.add_argument("--image", type=int, required=True, metavar="N", help="Its place in the set, from 1.")
    parser.add_argument("--file", metavar="NAME", help="The image's file: found by it, as upscales queued before add images.")
    parser.add_argument("--method", choices=METHODS, default="seedvr2",
                        help="seedvr2: redraws the detail, minutes (the default). fast: Superscale-SP, seconds, adds no new content. "
                             "ultrasharp: 4x-UltraSharp, seconds, the picture as it is with crisper edges.")
    parser.add_argument("--strength", type=float, default=1.0, help="With fast or ultrasharp: how much of the model's result, 0-1, the rest a plain resize.")
    parser.add_argument("--denoise", type=float, default=None,
                        help="With seedvr2: its latent noise, 0-1 (0 unless set), so it draws more. With usdu: how much is drawn again.")
    parser.add_argument("--resolution", type=int, default=0, metavar="PX",
                        help="With seedvr2: the shorter side to make it, as the Krea 2 workflow's 720p/1080p/1440p/4K. 0: twice what it is.")
    args = parser.parse_args(argv)
    state = RunState.load(args.resume)
    if state and args.file:
        found = next((i for i, shot in enumerate(state.shots or [], 1) if shot.get("file") == args.file), None)
        if not found:
            print(f"❌ {args.file} is no longer in the set.")
            return 1
        args.image = found
    if not state or not 1 <= args.image <= len(state.shots or []) or not state.shots[args.image - 1].get("file"):
        print(f"❌ No image {args.image} in a set called '{args.resume}'.")
        return 1
    print(f"🗂️ Run folder: {state.id}")
    comfy = UpscaleClient()
    if not comfy.wait_until_reachable():
        print(f"❌ ComfyUI isn't running at {comfy.url}.")
        return 1
    try:
        upscale(state, args.image, comfy, args.method, min(1.0, max(0.0, args.strength)), max(0, args.resolution),
                None if args.denoise is None else min(1.0, max(0.0, args.denoise)))
    except (RuntimeError, OSError) as e:
        print(f"❌ Could not upscale it: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
