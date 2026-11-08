"""
Continuous clips with Herrgotts H3 Infinite Continuation Suite (a ComfyUI node pack): clip 1 from its Start node,
every clip after from its Continue node, which carries the clip before's video and audio latent over in place
(Native Masked AV), and the film from its Saved Chain stitcher. Each clip saves its full AV latent in ComfyUI's
output folder, numbered, so the next clip continues from it and a stopped run continues where it was.

The suite needs MiniMax H3's first/last-frame model (FL2VA). The text encoder and both VAEs come from your H3
reference workflow, as H3 Multishot's do; the reference model and its LoRAs are for reference-to-video and stay out.
"""
import copy

from core.saved_workflows import _upstream
from pipelines.video import h3_multishot

PACK = "Herrgotts H3 Infinite Continuation Suite"
START, CONTINUE = "H3ContinuousStartV14", "H3ContinuousContinueV14"
ANALYZE, OUTPUT = "H3ContinuousAnalyzeHandoverV14", "H3ContinuousStitchOutputV14"
SAVE, LOAD, STITCH = "H3ContinuousSaveLatent", "H3ContinuousLoadLatent", "H3ContinuousStitchSavedChainV14"
NODES = (START, CONTINUE, ANALYZE, OUTPUT, SAVE, LOAD, STITCH)
FL2VA_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
# The suite's recommended v1.4 sampling: Sigma Shift 12 / 3, res_multistep, simple, 15 steps.
STEPS, SHIFT_VIDEO, SHIFT_AUDIO = 15, 12.0, 3.0
FPS = 24
# Under ComfyUI's output folder: each run's latents in a folder of their own.
LATENTS = "autogen_h3_infinite"


def supports(workflow):
    """An H3 reference workflow gives the encoder and VAEs; the model is the suite's own FL2VA."""
    return h3_multishot.supports(workflow)


def supports_path(path):
    return h3_multishot.supports_path(path)


def latent_folder(run_id):
    return f"{LATENTS}/{run_id}"


def defaults(info):
    """
    A node's settings as its author set them, from ComfyUI's /object_info entry: every widget's default, a list's
    first choice. Connections (IMAGE, LATENT and so on) are left for the graph to fill.
    """
    values = {}
    for group in ("required", "optional"):
        for name, spec in (info.get("input", {}).get(group) or {}).items():
            kind = spec[0] if isinstance(spec, (list, tuple)) and spec else None
            options = spec[1] if isinstance(spec, (list, tuple)) and len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(kind, list):
                values[name] = options.get("default", kind[0] if kind else None)
            elif kind in ("INT", "FLOAT", "BOOLEAN", "STRING") and "default" in options and not options.get("forceInput"):
                values[name] = options["default"]
            elif kind == "COMBO" and options.get("options"):
                values[name] = options.get("default", options["options"][0])
    return values


class _Graph:
    def __init__(self, workflow):
        self.links = h3_multishot.sources(workflow)
        self.graph = copy.deepcopy(_upstream(workflow, [self.links[name][0] for name in ("clip", "video_vae", "audio_vae")]))
        self.next_id = max([int(node_id) for node_id in workflow if str(node_id).isdigit()] + [0]) + 1

    def add(self, kind, inputs, info=None):
        node_id = str(self.next_id)
        self.next_id += 1
        self.graph[node_id] = {"class_type": kind, "inputs": {**defaults(info or {}), **inputs}}
        return [node_id, 0]


def build_clip(workflow, info, run_id, index, prompt, seconds, width, height, seed, first_frame=None, last_frame=None,
               previous=None, steps=STEPS):
    """
    One clip's graph: Start for the first, Continue from the clip before's saved latent after it. It saves this
    clip's full AV latent as slot index + 1 (a retry overwrites it) and renders the whole clip to look at.
    info is ComfyUI's /object_info for the suite's nodes. previous names the version of the clip before, say its
    file's time: the loader has no way to tell ComfyUI its file changed, so after a redo ComfyUI would hand the next
    clip the old latent from its cache. As an input of its own the loader never sees it, but the cache does.
    """
    if not prompt.strip():
        raise RuntimeError("Every clip needs a prompt.")
    g = _Graph(workflow)
    clip, video_vae, audio_vae = g.links["clip"], g.links["video_vae"], g.links["audio_vae"]
    unet = g.add("UNETLoader", {"unet_name": FL2VA_MODEL, "weight_dtype": "default"})
    # At the clip's own size, as a frame of it.
    scaled = lambda image: g.add("ImageScale", {"image": g.add("LoadImage", {"image": image}), "upscale_method": "lanczos",
                                                "width": width, "height": height, "crop": "center"})
    frames = {}
    if first_frame and index == 0:
        frames["first_frame"] = scaled(first_frame)
    if last_frame:
        frames["last_frame"] = scaled(last_frame)
    common = {"clip": clip, "vae": video_vae, "prompt": prompt, "width": width, "height": height,
              "duration": float(seconds), "ref_image_size": "match", **frames}
    if index == 0:
        conditioning = g.add(START, common, info[START])
        head = None
    else:
        loaded = g.add(LOAD, {"latent_path": latent_folder(run_id), "clip_index": index,
                               "autogen_previous": str(previous or "")}, info[LOAD])
        conditioning = g.add(CONTINUE, {**common, "previous_latent": loaded, "handover": [loaded[0], 3],
                                        "masked_context_frames": "39", "audio_feather_ticks": 0,
                                        "duration_mode": "Net New Content", "audio_tail_carryover": "Full Previous Tail"},
                             info[CONTINUE])
        head = [conditioning[0], 2]
    model = g.add("MiniMaxH3SigmaShift", {"model": unet, "shift_video": SHIFT_VIDEO, "shift_audio": SHIFT_AUDIO})
    sampled = g.add("SamplerCustomAdvanced", {
        "noise": g.add("RandomNoise", {"noise_seed": seed}),
        "guider": g.add("BasicGuider", {"model": model, "conditioning": conditioning}),
        "sampler": g.add("KSamplerSelect", {"sampler_name": "res_multistep"}),
        "sigmas": g.add("BasicScheduler", {"scheduler": "simple", "steps": steps, "denoise": 1.0, "model": model}),
        "latent_image": [conditioning[0], 1]})
    images = g.add("VAEDecode", {"samples": sampled, "vae": video_vae})
    audio = g.add("VAEDecodeAudio", {"samples": sampled, "vae": audio_vae})
    handover = g.add(ANALYZE, {"images": images}, info[ANALYZE])
    with_head = {"head_context_frames": head} if head else {}
    g.add(SAVE, {"latent": sampled, "filename_prefix": f"{latent_folder(run_id)}/clip", "clip_index": index + 1,
                 "handover": handover, **with_head}, info[SAVE])
    shown = g.add(OUTPUT, {"images": images, "output_mode": "Full", "handover": handover, "audio": audio, **with_head},
                  info[OUTPUT])
    g.add("VHS_VideoCombine", {"images": shown, "audio": [shown[0], 1], "frame_rate": FPS, "loop_count": 0,
                               "filename_prefix": "pipeline", "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                               "crf": 19, "save_metadata": False, "trim_to_audio": False, "pingpong": False,
                               "save_output": False})
    return g.graph


def build_stitch(workflow, info, run_id, count, film_prefix):
    """The film from the saved latents 1 to count, with the suite's seam crossfade and audio de-click."""
    g = _Graph(workflow)
    g.add(STITCH, {"video_vae": g.links["video_vae"], "audio_vae": g.links["audio_vae"],
                   "latent_prefix": f"{latent_folder(run_id)}/clip", "first_clip": 1, "last_clip": count,
                   "filename_prefix": film_prefix}, info[STITCH])
    return g.graph
