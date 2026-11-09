"""
Upscales spliced into the set's own workflow, after its last sampler (KSampler, ClownsharKSampler (RES4LYF),
SamplerCustom or SamplerCustomAdvanced with a guider):

    usdu:       Ultimate SD Upscale. 4x-UltraSharp makes it bigger, then the set's model redraws it in tiles at a low
                denoise, so a big image never has to fit on the card at once.
    ultrasharp: 4x-UltraSharp alone: the picture as it is, bigger, with crisper edges.
    seedvr2:    SeedVR2, which draws finer detail, as the Krea 2 workflow runs it on a 12 GB card.

In Generate each ends at the exact size chosen. (A Hires fix second pass was tried and left out: on these turbo
models a partial denoise came out noisy.)
"""
import math

SAMPLERS = ("KSampler", "KSamplerAdvanced", "ClownsharKSampler_Beta", "ClownsharKSampler", "SamplerCustom", "SamplerCustomAdvanced")
DECODERS = ("VAEDecode", "VAEDecodeTiled")
UPSCALE_MODEL = "4x-UltraSharp.pth"
# What KSampler (and so Ultimate SD Upscale) knows: a sampler of another kind, such as RES4LYF's, is run as euler.
KSAMPLER_SAMPLERS = ("euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_sde", "res_multistep", "uni_pc", "ddim", "lcm", "er_sde")
# RES4LYF's samplers that it adds to KSampler's list, under their own names.
RES4LYF_SAMPLERS = ("res_2s", "res_3s", "res_2m", "res_3m", "res_5s", "res_6s", "deis_2m", "deis_3m")
KSAMPLER_SCHEDULERS = ("simple", "normal", "karras", "exponential", "sgm_uniform", "beta", "linear_quadratic", "ddim_uniform")
# The noise the tiles start from, as a share of all of it: these are all flow models (Krea 2, Qwen-Image, Fibo,
# MOSS), whose sigmas run 1 to 0. A plain "denoise 0.3" on their shifted schedules started near 0.56, enough for each
# tile to draw a picture of its own (faces and bodies in every tile); this starts at the denoise and goes evenly down.
# Lightly, as Krea 2's own second pass refines (0.2 in ceil(0.2 x 8) = 2 steps of res_2s): eight steps from 0.3 over
# 4x-UltraSharp's crisp edges baked its grain into specks and a cracked skin; two from 0.2 keep the sharpness clean.
DENOISE = {"usdu": 0.2}
LEAST_STEPS = 2
TILE = 768


class Unsupported(RuntimeError):
    """The workflow samples in a way these can't follow."""


def _ancestors(api, node_id, seen=None):
    seen = set() if seen is None else seen
    for value in api.get(node_id, {}).get("inputs", {}).values():
        if isinstance(value, list) and len(value) == 2 and str(value[0]) in api and str(value[0]) not in seen:
            seen.add(str(value[0]))
            _ancestors(api, str(value[0]), seen)
    return seen


def last_sampler(api):
    """(decoder, sampler): the decoder of the final image and the sampler it reads. A first pass feeding a second isn't it."""
    found = [(node_id, str(node["inputs"]["samples"][0])) for node_id, node in api.items()
             if node.get("class_type") in DECODERS and isinstance(node["inputs"].get("samples"), list)
             and api.get(str(node["inputs"]["samples"][0]), {}).get("class_type") in SAMPLERS]
    if not found:
        raise Unsupported("This workflow has no sampler decoded into its image that a refining upscale can follow.")
    later = [pair for pair in found if not any(pair[1] in _ancestors(api, other[1]) for other in found if other is not pair)]
    return (later or found)[-1]


def _show_only(api, image):
    """
    The upscale's image shown, and everything it doesn't need taken out: the workflow's own saves, and whatever ran
    after its sampler (a SeedVR2 pass, a comparer), which would otherwise run too.
    """
    api["ru_show"] = {"class_type": "PreviewImage", "inputs": {"images": image}, "_meta": {"title": "Upscaled"}}
    needed = _ancestors(api, "ru_show") | {"ru_show"}
    for node_id in [node_id for node_id in api if node_id not in needed]:
        del api[node_id]


def _refine_sigmas(api, denoise, steps):
    """
    From denoise down to 0 in steps, evenly (ManualSigmas): the noise the tiles start from is the denoise asked for,
    whatever shift the model's own schedule has.
    """
    from core.workflow_options import custom_sigmas
    api["ru_sigmas"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": custom_sigmas(denoise, refine_steps(denoise, steps))},
                        "_meta": {"title": "Refine: from the denoise down"}}
    return ["ru_sigmas", 0]


def refine_steps(denoise, steps):
    """As many of the set's steps as the denoise is a share of (ceil(0.2 x 8) = 2), at least LEAST_STEPS."""
    return max(LEAST_STEPS, math.ceil(denoise * steps - 1e-9))


def _sampler_name(sampler, kind):
    """
    The set's own sampler, as KSampler knows it: RES4LYF's "exponential/res_2s" is res_2s there, as that pack, which
    a ClownsharKSampler workflow has, adds its samplers to KSampler's. Else euler.
    """
    given = str(sampler.get("sampler_name") or "")
    if given in KSAMPLER_SAMPLERS:
        return given
    if kind.startswith("ClownsharKSampler") and given.rsplit("/", 1)[-1] in RES4LYF_SAMPLERS:
        return given.rsplit("/", 1)[-1]
    return "euler"


def _load(api, uploaded):
    api["ru_load"] = {"class_type": "LoadImage", "inputs": {"image": uploaded}, "_meta": {"title": "Image to upscale"}}
    return ["ru_load", 0]


def _number(api, value, default):
    """A literal, or what a primitive node feeding it holds, or the default."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, list):
        source = api.get(str(value[0]), {}).get("inputs", {})
        found = next((v for k, v in source.items() if k in ("value", "int", "float", "steps", "seed", "noise_seed")
                      and isinstance(v, (int, float)) and not isinstance(v, bool)), None)
        if found is not None:
            return found
    return default


def _tiled(api, sampler_id, vae, image, scale, denoise, seed=777):
    """Ultimate SD Upscale on an image with the set's sampler's model and prompts. Returns the link to the image it makes."""
    sampler, kind = api[sampler_id]["inputs"], api[sampler_id]["class_type"]
    api["ru_model"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}, "_meta": {"title": "4x-UltraSharp"}}
    common = {"image": image, "vae": vae, "upscale_by": scale, "seed": seed,
              "upscale_model": ["ru_model", 0], "mode_type": "Chess", "tile_width": TILE, "tile_height": TILE, "mask_blur": 16,
              "tile_padding": 32, "seam_fix_mode": "None", "seam_fix_denoise": 1.0, "seam_fix_width": 64, "seam_fix_mask_blur": 8,
              "seam_fix_padding": 16, "force_uniform_tiles": True, "tiled_decode": False, "batch_size": 1}
    if kind == "SamplerCustomAdvanced":
        if not isinstance(sampler.get("sigmas"), list):
            raise Unsupported("Its sampler has no schedule to take a denoise from.")
        steps = int(_number(api, api.get(str(sampler["sigmas"][0]), {}).get("inputs", {}).get("steps"), 8))
        node = {"class_type": "UltimateSDUpscaleGuider", "inputs": {
            **common, "guider": sampler["guider"], "sampler": sampler["sampler"], "sigmas": _refine_sigmas(api, denoise, steps)}}
    elif "positive" in sampler and "negative" in sampler and "model" in sampler:
        steps = int(_number(api, sampler.get("steps"), 8))
        cfg = float(_number(api, sampler.get("cfg"), 1.0))
        inputs = {**common, "model": sampler["model"], "positive": sampler["positive"], "negative": sampler["negative"],
                  "seed": int(_number(api, sampler.get("seed", sampler.get("noise_seed")), seed)), "steps": steps, "cfg": cfg,
                  "sampler_name": _sampler_name(sampler, kind),
                  "scheduler": sampler.get("scheduler") if sampler.get("scheduler") in KSAMPLER_SCHEDULERS else "simple",
                  "denoise": denoise}
        if kind == "SamplerCustom" and isinstance(sampler.get("sampler"), list):
            custom = sampler["sampler"]  # Its own sampler, as it made the image
        else:
            # The set's own sampler, as its second pass refines with it (res_2s for Krea 2).
            api["ru_sampler"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": inputs["sampler_name"]},
                                 "_meta": {"title": "Refine: sampler"}}
            custom = ["ru_sampler", 0]
        inputs.update(custom_sampler=custom, custom_sigmas=_refine_sigmas(api, denoise, steps))
        node = {"class_type": "UltimateSDUpscaleCustomSample", "inputs": inputs}
    else:
        raise Unsupported("Its sampler doesn't take a model and prompts that Ultimate SD Upscale can use.")
    node["_meta"] = {"title": "Ultimate SD Upscale"}
    api["ru_usdu"] = node
    return ["ru_usdu", 0]


def usdu(api, uploaded, scale=2.0, denoise=DENOISE["usdu"], seed=777):
    """The set's workflow as Ultimate SD Upscale of the uploaded image, 4x-UltraSharp then tiles redrawn."""
    decoder, sampler_id = last_sampler(api)
    _show_only(api, _tiled(api, sampler_id, api[decoder]["inputs"]["vae"], _load(api, uploaded), scale, denoise, seed))
    return api


SPLICES = {"usdu": usdu}


def _sharpened(api, image):
    """4x-UltraSharp: the picture as it was, four times as big, with crisper edges."""
    api["ru_model"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}, "_meta": {"title": "4x-UltraSharp"}}
    api["ru_sharp"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["ru_model", 0], "image": image},
                       "_meta": {"title": "UltraSharp"}}
    return ["ru_sharp", 0]


# SeedVR2 as pipelines/image/upscale.py runs it on this 12 GB card: the 7B model, 36 blocks swapped to the CPU, tiled VAE.
SEEDVR2 = ("SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel", "SeedVR2VideoUpscaler")


def _seedvr2(api, image, shorter, denoise=0.0):
    from pipelines.image.upscale import DIT_MODEL, VAE_MODEL
    api["ru_dit"] = {"class_type": "SeedVR2LoadDiTModel", "_meta": {"title": "SeedVR2: model"}, "inputs": {
        "model": DIT_MODEL, "device": "cuda:0", "blocks_to_swap": 36, "swap_io_components": False,
        "offload_device": "cpu", "cache_model": False, "attention_mode": "sageattn_2"}}
    api["ru_vae"] = {"class_type": "SeedVR2LoadVAEModel", "_meta": {"title": "SeedVR2: VAE"}, "inputs": {
        "model": VAE_MODEL, "device": "cuda:0", "encode_tiled": True, "encode_tile_size": 1024, "encode_tile_overlap": 128,
        "decode_tiled": True, "decode_tile_size": 1024, "decode_tile_overlap": 128, "tile_debug": "false",
        "offload_device": "cpu", "cache_model": False}}
    api["ru_seedvr2"] = {"class_type": "SeedVR2VideoUpscaler", "_meta": {"title": "SeedVR2"}, "inputs": {
        "image": image, "dit": ["ru_dit", 0], "vae": ["ru_vae", 0], "seed": 777, "resolution": shorter, "max_resolution": 0,
        "batch_size": 1, "uniform_batch_size": False, "color_correction": "lab", "temporal_overlap": 0, "prepend_frames": 0,
        "input_noise_scale": 0.0, "latent_noise_scale": float(denoise or 0), "offload_device": "cpu", "enable_debug": False}}
    return ["ru_seedvr2", 0]


# In Generate: each image of the set upscaled as it is made, before the workflow saves it. {what the page says: method}
# Ultimate SD is left out: its tiles, redrawn by these flow models, came out noisy rather than sharper.
IN_GENERATION = {"UltraSharp": "ultrasharp", "SeedVR2": "seedvr2"}
# What a 12 GB card takes without running out of memory (or stalling long enough for Windows to reset the driver, as a
# 4x-UltraSharp pass over a 3.6 MP Krea 2 image did with Krea 2 still loaded): the most megapixels the image may be
# before (4x-UltraSharp works at four times its size), the most it may end at, and for SeedVR2 its shorter side.
LIMITS = {"Ultimate SD": {"base": 2.0, "final": 16.0}, "UltraSharp": {"base": 2.0, "final": 16.0},
          "SeedVR2": {"base": 4.0, "final": 8.3, "shorter": 2160}}
MOST_SCALE = 4.0


def parse_final(text):
    """'2560x1440' as (2560, 1440), or None."""
    try:
        width, height = (int(side) for side in str(text).lower().split("x"))
    except (TypeError, ValueError):
        return None
    return (width, height) if 64 <= width <= 8192 and 64 <= height <= 8192 else None


def in_generation(api, method, final, scale=2.0, denoise=None, free_memory=True):
    """
    The set's workflow with its image upscaled to final (width, height) before it is saved: what read the decoded
    image (its save, and anything after it such as a sharpen) reads the upscaled one instead. scale is about how many
    times bigger that is, for Ultimate SD's tiles. free_memory: the set's model unloaded first (FreeMemoryImage), so
    the upscaler never shares the card with it. Raises Unsupported.
    """
    decoder, sampler_id = last_sampler(api)
    made = [decoder, 0]
    readers = [(node, name) for node in api.values() for name, value in node["inputs"].items() if value == made]
    vae = api[decoder]["inputs"]["vae"]
    image = made
    if free_memory:
        api["ru_free"] = {"class_type": "FreeMemoryImage", "inputs": {"image": made, "aggressive": False}, "_meta": {"title": "Free VRAM"}}
        image = ["ru_free", 0]
    scale = min(MOST_SCALE, max(1.0, float(scale)))
    if method == "ultrasharp":
        image = _sharpened(api, image)
    elif method == "usdu":
        image = _tiled(api, sampler_id, vae, image, scale, DENOISE["usdu"] if denoise is None else denoise)
    elif method == "seedvr2":
        image = _seedvr2(api, image, min(final), denoise or 0)
    else:
        raise Unsupported(f"No upscale called {method}.")
    # Exactly the size chosen: each of these comes out near it, on its own grid.
    api["ru_size"] = {"class_type": "ImageScale", "inputs": {"image": image, "upscale_method": "lanczos", "width": final[0],
                                                             "height": final[1], "crop": "center"}, "_meta": {"title": "Upscale: to size"}}
    for node, name in readers:
        node["inputs"][name] = ["ru_size", 0]
    return api
