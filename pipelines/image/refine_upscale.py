"""
Upscales that draw again with the set's own model and prompt: the image made bigger, then redrawn a little.

    hires: "Hires fix". The image back into a latent (VAE Encode), that made twice as big (Latent Upscale By), then a
           second pass of the set's own sampler at a low denoise: skin, hair and texture that weren't there.
    usdu:  Ultimate SD Upscale. 4x-UltraSharp makes it bigger, then the set's model redraws it in tiles at a low
           denoise, so a big image never has to fit on the card at once.

Both start from the workflow the set was made with, filled in as for its own image, and splice in after its last
sampler: KSampler, ClownsharKSampler (RES4LYF), SamplerCustom or SamplerCustomAdvanced with a guider.
"""
SAMPLERS = ("KSampler", "KSamplerAdvanced", "ClownsharKSampler_Beta", "ClownsharKSampler", "SamplerCustom", "SamplerCustomAdvanced")
DECODERS = ("VAEDecode", "VAEDecodeTiled")
UPSCALE_MODEL = "4x-UltraSharp.pth"
# What KSampler (and so Ultimate SD Upscale) knows: a sampler of another kind, such as RES4LYF's, is run as euler.
KSAMPLER_SAMPLERS = ("euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_sde", "res_multistep", "uni_pc", "ddim", "lcm", "er_sde")
KSAMPLER_SCHEDULERS = ("simple", "normal", "karras", "exponential", "sgm_uniform", "beta", "linear_quadratic", "ddim_uniform")
DENOISE = {"hires": 0.35, "usdu": 0.3}
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


def _denoised_sigmas(api, sigmas, denoise):
    """The tail of a schedule, for a denoise: SplitSigmasDenoise's low sigmas."""
    api["ru_split"] = {"class_type": "SplitSigmasDenoise", "inputs": {"sigmas": sigmas, "denoise": denoise},
                       "_meta": {"title": "Refine: denoise"}}
    return ["ru_split", 1]


def hires(api, uploaded, scale=2.0, denoise=DENOISE["hires"]):
    """The set's workflow as a Hires fix of the uploaded image."""
    decoder, sampler_id = last_sampler(api)
    sampler = api[sampler_id]["inputs"]
    api["ru_load"] = {"class_type": "LoadImage", "inputs": {"image": uploaded}, "_meta": {"title": "Image to upscale"}}
    api["ru_encode"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["ru_load", 0], "vae": api[decoder]["inputs"]["vae"]},
                        "_meta": {"title": "Hires fix: encode"}}
    api["ru_latent"] = {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["ru_encode", 0], "upscale_method": "bislerp", "scale_by": scale},
                        "_meta": {"title": "Hires fix: upscale latent"}}
    sampler["latent_image"] = ["ru_latent", 0]
    kind = api[sampler_id]["class_type"]
    if "denoise" in sampler or kind in ("KSampler", "ClownsharKSampler_Beta", "ClownsharKSampler"):
        sampler["denoise"] = denoise
    elif kind == "KSamplerAdvanced":
        steps = sampler.get("steps")
        if not isinstance(steps, int):
            raise Unsupported("Its sampler's steps come from elsewhere, so a denoise can't be set on it.")
        sampler["start_at_step"] = round(steps * (1 - denoise))
        sampler["add_noise"] = "enable"
    elif isinstance(sampler.get("sigmas"), list):
        sampler["sigmas"] = _denoised_sigmas(api, sampler["sigmas"], denoise)
    else:
        raise Unsupported("Its sampler has no denoise to set.")
    _show_only(api, [decoder, 0])
    return api


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


def usdu(api, uploaded, scale=2.0, denoise=DENOISE["usdu"], seed=777):
    """The set's workflow as Ultimate SD Upscale of the uploaded image, 4x-UltraSharp then tiles redrawn."""
    decoder, sampler_id = last_sampler(api)
    sampler, kind = api[sampler_id]["inputs"], api[sampler_id]["class_type"]
    api["ru_load"] = {"class_type": "LoadImage", "inputs": {"image": uploaded}, "_meta": {"title": "Image to upscale"}}
    api["ru_model"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}, "_meta": {"title": "4x-UltraSharp"}}
    common = {"image": ["ru_load", 0], "vae": api[decoder]["inputs"]["vae"], "upscale_by": scale, "seed": seed,
              "upscale_model": ["ru_model", 0], "mode_type": "Chess", "tile_width": TILE, "tile_height": TILE, "mask_blur": 16,
              "tile_padding": 32, "seam_fix_mode": "None", "seam_fix_denoise": 1.0, "seam_fix_width": 64, "seam_fix_mask_blur": 8,
              "seam_fix_padding": 16, "force_uniform_tiles": True, "tiled_decode": False, "batch_size": 1}
    if kind == "SamplerCustomAdvanced":
        if not isinstance(sampler.get("sigmas"), list):
            raise Unsupported("Its sampler has no schedule to take a denoise from.")
        node = {"class_type": "UltimateSDUpscaleGuider", "inputs": {
            **common, "guider": sampler["guider"], "sampler": sampler["sampler"], "sigmas": _denoised_sigmas(api, sampler["sigmas"], denoise)}}
    elif "positive" in sampler and "negative" in sampler and "model" in sampler:
        given = sampler.get("sampler_name")
        steps = int(_number(api, sampler.get("steps"), 8))
        cfg = float(_number(api, sampler.get("cfg"), 1.0))
        inputs = {**common, "model": sampler["model"], "positive": sampler["positive"], "negative": sampler["negative"],
                  "seed": int(_number(api, sampler.get("seed", sampler.get("noise_seed")), seed)), "steps": steps, "cfg": cfg,
                  "sampler_name": given if given in KSAMPLER_SAMPLERS else "euler",
                  "scheduler": sampler.get("scheduler") if sampler.get("scheduler") in KSAMPLER_SCHEDULERS else "simple",
                  "denoise": denoise}
        if kind == "SamplerCustom" and isinstance(sampler.get("sigmas"), list) and isinstance(sampler.get("sampler"), list):
            # Its own sampler and schedule, as it made the image.
            inputs.update(custom_sampler=sampler["sampler"], custom_sigmas=_denoised_sigmas(api, sampler["sigmas"], denoise))
            node = {"class_type": "UltimateSDUpscaleCustomSample", "inputs": inputs}
        else:
            node = {"class_type": "UltimateSDUpscale", "inputs": inputs}
    else:
        raise Unsupported("Its sampler doesn't take a model and prompts that Ultimate SD Upscale can use.")
    node["_meta"] = {"title": "Ultimate SD Upscale"}
    api["ru_usdu"] = node
    _show_only(api, ["ru_usdu", 0])
    return api


SPLICES = {"hires": hires, "usdu": usdu}
