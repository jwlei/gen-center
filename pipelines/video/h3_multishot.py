"""Build a single-take H3 Multishot graph from an H3 reference workflow."""
import copy
import json

from core.saved_workflows import _upstream
from pipelines.video import h3_prompt

SAMPLER = "H3MultishotSampler"


def sources(workflow):
    """Return the model, text encoder and VAEs used by an unambiguous H3 reference sampler."""
    references = [(node_id, node) for node_id, node in workflow.items()
                  if node.get("class_type") == h3_prompt.REFERENCE_NODE]
    if len(references) != 1:
        raise RuntimeError("H3 Multishot needs a workflow with one MiniMax H3 reference-to-video node.")
    node_id, reference = references[0]
    samplers = [node for node in workflow.values()
                if node.get("class_type") == "SamplerCustomAdvanced"
                and node.get("inputs", {}).get("latent_image") == [node_id, 1]]
    if len(samplers) != 1:
        raise RuntimeError("H3 Multishot could not identify the reference workflow's sampler.")
    guider_link = samplers[0]["inputs"].get("guider")
    guider = workflow.get(guider_link[0], {}) if isinstance(guider_link, list) and len(guider_link) == 2 else {}
    found = {"model": guider.get("inputs", {}).get("model"),
             **{name: reference.get("inputs", {}).get(source)
                for name, source in (("clip", "clip"), ("video_vae", "vae"), ("audio_vae", "audio_vae"))}}
    if any(not isinstance(link, list) or len(link) != 2 or link[0] not in workflow for link in found.values()):
        raise RuntimeError("H3 Multishot could not identify the workflow's model, encoder and VAEs.")
    return found


def supports(workflow):
    try:
        sources(workflow)
        return True
    except RuntimeError:
        return False


def supports_path(path):
    if not path:
        return False
    try:
        with open(path, encoding="utf-8") as file:
            return supports(json.load(file))
    except (OSError, ValueError):
        return False


def build(workflow, prompts, images, seconds, width, height, seed, first_frame=False, steps=20):
    """Return an independent graph rendering all shots and audio in one ComfyUI job."""
    if not prompts or any(not prompt.strip() for prompt in prompts):
        raise RuntimeError("Every H3 Multishot shot needs a prompt.")
    if first_frame and not images:
        raise RuntimeError("H3 Multishot needs an image to use as its first frame.")
    links = sources(workflow)
    graph = copy.deepcopy(_upstream(workflow, [link[0] for link in links.values()]))
    next_id = max([int(node_id) for node_id in workflow if str(node_id).isdigit()] + [0]) + 1

    def add(kind, inputs):
        nonlocal next_id
        node_id = str(next_id)
        next_id += 1
        graph[node_id] = {"class_type": kind, "inputs": inputs}
        return [node_id, 0]

    image_links = []
    for image in images:
        loaded = add("LoadImage", {"image": image})
        image_links.append(add("ImageScale", {"image": loaded, "upscale_method": "lanczos",
                                             "width": width, "height": height, "crop": "center"}))
    inputs = {**links, "script": json.dumps({"prompts": prompts}, ensure_ascii=False), "shot_count": 0,
              "width": width, "height": height, "frames_per_shot": h3_prompt.clip_frames(seconds),
              "seed": seed, "steps": steps, "seed_per_shot": True}
    if image_links:
        batch = image_links[0]
        for link in image_links[1:]:
            batch = add("ImageBatch", {"image1": batch, "image2": link})
        inputs["reference_images"] = batch
        if first_frame:
            inputs["start_image"] = image_links[0]
    sampler = add(SAMPLER, inputs)
    add("VHS_VideoCombine", {"images": sampler, "audio": [sampler[0], 1], "frame_rate": 24,
                             "loop_count": 0, "filename_prefix": "pipeline", "format": "video/h264-mp4",
                             "pix_fmt": "yuv420p", "crf": 19, "save_metadata": False,
                             "trim_to_audio": False, "pingpong": False, "save_output": False})
    return graph
