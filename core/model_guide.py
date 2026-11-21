"""
A short guide to each diffusion model the workflows run, for the link under the workflow picker: what it is good and
bad at, which sizes and steps suit it, how to prompt it, its LoRAs, what fits a 12 GB card, and its licence. Written
for a phone: short lines under headings that fold.

Each guide is {title, lead, facts: [(what, value)], sections: [{title, items}], faq: [(question, answer)], sources:
[(name, url)]}, in its model family's file in core/models/; the two here are no model's. panel_notes() adds what this panel itself holds the model to (pipelines/image/models.py and
pipelines/video/media.py), so the guide and the limits it describes can't drift apart.

Facts are from the model cards, ComfyUI's docs and workflow templates (read November 2026). What could not be
confirmed is said so ("unverified"). Licences are summarised, not quoted: read them before selling what is made.
"""
import json

from core import models as known_models
from core import saved_workflows as sw

FIBO2, KREA2, MOSS, QWEN_EDIT = "fibo2", "krea2", "moss_image", "qwen_image_edit"
QWEN21, H3_IMAGE, H3_VIDEO, LTX23 = "qwen_image_21", "minimax_h3_image", "minimax_h3_video", "ltx23"
# Not a model: how a film's clips are joined (the "How clips connect" choice), with a guide of its own.
CONNECTION = "clip_connection"
STYLE_LORA = "style_lora"
# What a workflow's model is called by pipelines/image/models.py, where its guide is another one's: the edit side of a
# model that makes and edits is the same model (its same_as in core/models/).
SAME_GUIDE = {model: entry.same_as for model, entry in known_models.IMAGE_MODELS.items() if entry.same_as}
# The built-in workflows, which the form lists without a saved copy in ComfyUI.
BUILT_IN = {"video": LTX23, "shorts": LTX23}

GUIDES = {
    STYLE_LORA: {
        "title": "Style LoRA",
        "lead": "A LoRA adds learned changes to a workflow's model, such as a visual style or subject, without replacing the model.",
        "facts": [
            ("Choose", "Use a LoRA made for the workflow's model and version."),
            ("Strength", "Controls its influence. Start with the creator's recommended value."),
            ("Prompt", "Some LoRAs need a trigger word or phrase in the prompt; check the creator's instructions."),
            ("Install", "Place LoRA files in ComfyUI's models/loras folder, or a configured model folder."),
        ],
        "sections": [
            {"title": "Choosing and using one", "items": [
                "Enable Use LoRA, choose a file and set its strength. Turn it off to use the workflow without that style LoRA.",
                "The picker matches model-family keywords in filenames and folders. A matching name is not proof of compatibility: check the LoRA's model and version.",
                "Files without a recognized family are hidden unless the workflow already uses them. Family words are removed from picker labels, not filenames.",
                "Check the creator's instructions for a trigger phrase, recommended strength, example prompts and licence.",
            ]},
            {"title": "Adjusting the look", "items": [
                "Higher strength generally makes the LoRA's influence stronger; compare a few values with the same prompt and seed.",
                "If the effect is weak, check the model version, trigger phrase and recommended strength before increasing it.",
                "Turbo LoRAs are separate: they change how a model generates in fewer steps, rather than simply adding a style.",
            ]},
        ],
        "faq": [
            ("Why is my LoRA missing?", "Check its filename or folder for the workflow's family keyword and confirm ComfyUI can see it. A file already used by the workflow can appear without a recognized keyword."),
            ("Why does it have little effect?", "Check compatibility, any trigger phrase and the creator's recommended strength. Matching a filename alone cannot guarantee compatibility."),
        ],
        "sources": [("ComfyUI LoRA guide", "https://docs.comfy.org/tutorials/basic/lora"),
                    ("Hugging Face adapter guide", "https://huggingface.co/docs/diffusers/main/en/using-diffusers/loading_adapters")],
    },
    CONNECTION: {
        "title": "How clips connect",
        "lead": "A film is made of clips. This is how each one is joined to the one before, and what that means for redoing a shot, for sound, and for how you write the prompt.",
        "facts": [
            ("Chain", "Clip N starts on the last frame of clip N-1. Any video model with at most one image."),
            ("Separate", "Every clip starts on your image (or the prompt), with a fade between."),
            ("Director", "A chain made by H3 Motion Director. Exactly one image."),
            ("Multishot", "All shots in one render, one take. H3 reference workflows."),
            ("Infinite", "Video and sound carry from clip to clip. H3 reference workflows."),
            ("Redo", "Continuous modes redo the shot and every one after it. Separate redoes only that clip."),
        ],
        "sections": [
            {"title": "Which to pick", "items": [
                "You want one unbroken scene, each shot picking up where the last ended: Chain, or Infinite on H3 if sound must carry on too.",
                "You want several unrelated moments built on your picture: Separate.",
                "You have one image and want H3 to move the camera and subject itself: Director.",
                "You want shots that share one voice and one look and never reset: Multishot.",
                "A single clip is always a separate moment: there is nothing to connect.",
                "With more than one image attached, only the modes that take several references are offered. If none is, clips are separate.",
            ]},
            {"title": "Chain: last frame to first frame", "items": [
                "After a clip is made, its last frame is taken (about half a second from the end) and becomes the next clip's start picture.",
                "Only that one picture is handed over. Motion, speed and sound do not carry, so a quick move can start again from rest.",
                "In the film, the first frame of every later clip is dropped so the shared frame isn't shown twice. The audio seams are about 0.03 s, with no video fade.",
                "Drift builds up a little at each join. Long chains slowly lose the face, the light or the colour: a reference image helps.",
                "The planning LLM is told each clip opens as the last one ended and must change something physical.",
            ]},
            {"title": "Separate moments", "items": [
                "Each clip starts from the attached image, or from the prompt alone if there is none, so no clip depends on another.",
                "Clips are joined with a short fade in and out of the picture and the sound.",
                "Redoing one clip leaves the rest alone. Clips can't show the same person unless the image or the prompt says so.",
            ]},
            {"title": "H3 Motion Director", "items": [
                "Works like Chain: the last frame of one clip starts the next, and they are joined the same way.",
                "Needs exactly one image. The panel picks Director's own mode: text only with no image, image to video with one image, reference to video when the image is a reference or there are several.",
                "Use it when you want Director's camera and subject control instead of the plain reference workflow.",
            ]},
            {"title": "H3 Multishot", "items": [
                "One ComfyUI job renders every shot, and the sound, as a single take. There is no hand-over between shots to see.",
                "All shots are the same length: it needs a fixed clip length. It can't be combined with first-clip-only, OpenH3-IR, a reference video or reference audio.",
                "Needs a workflow with exactly one MiniMax H3 reference node. Image 1 can also be the first frame, if you tick that.",
                "Each shot uses its own seed. The sampling steps are set under the choice.",
                "The prompt is flattened to plain text per shot, marked [Shot 1], [Shot 2]. A redo renders the whole take again.",
                "The node pack (ComfyUI-H3-Multishot) says each shot should open holding the last one's closing arrangement for about two seconds before anyone speaks, and end settled with the speech finished.",
                "Its notes: a spoken line must never straddle two shots; repeat each character's and the room's description word for word in every shot; change something physical in every shot.",
                "Its notes: 124 frames (about 5 s) is too short to hold that quiet at the start and end, so the join clips. 243 frames (about 10 s) suits one short line, 362 (about 15 s) is the trained longest.",
                "Its notes: the camera may cut inside a shot, and the sound stays continuous. Keep 24 fps, other rates shift voices.",
            ]},
            {"title": "H3 Infinite continuation", "items": [
                "Uses Herrgott's H3 Infinite Continuation Suite (a ComfyUI custom node pack, GPL-3.0). It continues from the previous clip's saved video and sound state, not just a picture.",
                "The start of each later clip is held by about 39 frames (1.6 s) of the previous clip, protected by masks, so motion and sound carry on.",
                "Image 1 is the first frame of clip 1. Image 2 is the last frame of clip 1, image 3 of clip 2, and so on. Any may be left out.",
                "The model makes its own sound. So it can't use OpenH3-IR, a reference video, reference audio, your own audio or narration.",
                "Saved states are kept in ComfyUI's output folder. A run that was stopped can carry on from them.",
                "The film is joined inside ComfyUI with the suite's own crossfade and click removal, so ComfyUI must be running at that moment.",
                "The suite needs a recent ComfyUI that has native H3 sound masks (ComfyUI pull request 15375).",
                "The suite can detect a frozen or unstable landing and move the hand-over up to 16 frames earlier. This is its own behaviour.",
                "Whether the suite's settings suit very long films is unverified here.",
            ]},
            {"title": "Writing for a continuous take", "items": [
                "Say what changes, not what stays: each shot should do something physical the last did not.",
                "Avoid stillness words such as \"holds still\" or \"does not move\": the whole frame can freeze.",
                "Don't change the scene at the very start of a shot. Change it part way through.",
                "Put the things that never change (looks, room, light) in the character section, and the action in the shot.",
                "Chain, Multishot and Infinite get these instructions from the panel. Separate moments get a fresh opening for each clip.",
            ]},
            {"title": "Sound", "items": [
                "In Multishot and Infinite the model makes one continuous sound for the film.",
                "In Chain, Director and Separate each clip has its own sound, joined at the seams (a short audio blend in Chain, a fade in Separate).",
                "Infinite can't use your own audio or narration, a reference video or reference audio, because it makes its own sound. Multishot can't use a reference video or reference audio.",
            ]},
        ],
        "faq": [
            ("Why do later shots look different from the first?", "Chain only carries one picture. Small changes add up at each join. Use a reference image, repeat the look in each shot's prompt, or try Infinite."),
            ("Why is a choice greyed out or missing?", "Director needs one image, and Multishot and Infinite need an H3 reference workflow. Chain needs at most one image."),
            ("Why did redoing one shot redo others?", "In a continuous mode every later shot began from the one you redid, so they must be made again. Use Separate if shots should stand alone."),
            ("Can I mix modes in one film?", "No. One mode joins all the clips of a film."),
            ("There is a visible jump at a join.", "In Chain the start picture is the same, but the motion starts again. Try Infinite, or write a shot that begins slowly."),
        ],
        "sources": [("ComfyUI H3 guide", "https://docs.comfy.org/tutorials/video/minimax/minimax-h3"),
                    ("ComfyUI H3 prompt guide", "https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide"),
                    ("H3 Infinite Continuation Suite", "https://github.com/HerrgottMargott/Herrgotts-H3-Infinite-Continuation-Suite"),
                    ("ComfyUI-H3-Multishot", "https://github.com/jlucasmcrell/ComfyUI-H3-Multishot")],
    },
}
# Each model's own, from its family's file (core/models/), beside these two that are no model's.
GUIDES.update(known_models.GUIDES)


def key_of(api, pipeline=None):
    """Which guide a workflow in API form has, or None: the model its nodes say it runs."""
    classes = {node.get("class_type", "") for node in api.values() if isinstance(node, dict)}
    # The picture model's nodes are MiniMaxH3Image...; the video ones are every other MiniMaxH3..., and ImageToVideo.
    if any(name.startswith("MiniMaxH3") and (not name.startswith("MiniMaxH3Image") or name == "MiniMaxH3ImageToVideo") for name in classes):
        return H3_VIDEO
    if classes & {"EmptyLTXVLatentVideo", "LTXVConditioning"}:
        return LTX23
    model = sw.image_model(api)
    key = SAME_GUIDE.get(model, model)
    return key if key in GUIDES else None


def key_for_path(path, pipeline=None):
    """key_of() the workflow file at path, or None if it can't be read."""
    try:
        with open(path, encoding="utf-8") as f:
            api = json.load(f)
        return key_of(api, pipeline) if isinstance(api, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def entry(key):
    """What the workflow list carries for the link: {key, title}, or None for a model with no guide."""
    return {"key": key, "title": GUIDES[key]["title"]} if key in GUIDES else None


def panel_notes(key):
    """What this panel holds the model to, as lines for the guide's own section."""
    from pipelines.image import models
    from pipelines.video import h3_infinite, h3_prompt, media, planner, run_eta
    notes = []
    if key == STYLE_LORA:
        return ["Style LoRA controls appear when the selected workflow exposes them. The file picker uses model-family keywords, not a full compatibility check."]
    if key == CONNECTION:
        low, high, usual = planner.CLIP_SECONDS[h3_prompt.MODEL]
        return [f"Clips are joined with a {media.FADE:g} s fade in Separate, and a {media.SEAM:g} s audio seam in Chain.",
                f"H3 clips run {low} to {high} s, {usual} s by default. LTX clips run {planner.MIN_SHOT_SECONDS} to {planner.MAX_SHOT_SECONDS} s.",
                f"Films are {media.FPS} frames per second.",
                f"Multishot samples {run_eta.MULTISHOT_STEPS} steps unless you change it (1 to 50). Infinite samples {h3_infinite.STEPS}."]
    if key in (LTX23, H3_VIDEO):
        if key == H3_VIDEO:
            return [f"Sizes up to 960x544 ({media.MOST_PIXELS['minimax_h3'] / 1e6:.2f} MP), which this card renders in a sensible time. Its own 768p is 1344x768."]
        return [f"Sizes up to {media.DEFAULT_SHAPE[0]}x{media.DEFAULT_SHAPE[1]} ({media.RENDER_AREA / 1e6:.2f} MP)."]
    # The image models this guide is for: its own, and an edit model that is the same model.
    ids = tuple(model for model, entry in known_models.IMAGE_MODELS.items() if key in (model, entry.same_as))
    for model in ids:
        most, least = models.most_megapixels(model), models.LEAST_MEGAPIXELS.get(model)
        start = models.DEFAULT_MEGAPIXELS.get(model)
        part = [f"up to {most:g} MP" if most else f"up to {media_max():g} MP (the form's own limit)"]
        if start:
            part.append(f"starts at {start:g} MP")
        elif least:
            part.append(f"starts at {least:g} MP")
        if models.MOST_IMAGES.get(model):
            part.append(f"{models.MOST_IMAGES[model]} references")
        if models.MOST_WRITTEN.get(model):
            part.append(f"the LLM writes {models.MOST_WRITTEN[model]} prompts per reply")
        label = "Edit" if model.endswith("_edit") and len(ids) > 1 else "Make" if len(ids) > 1 else ""
        notes.append(f"{label + ': ' if label else ''}{', '.join(part)}.")
    return notes


def media_max():
    from pipelines.image import media
    return media.MAX_MEGAPIXELS


def guide(key):
    """The guide for the page, with what this panel holds the model to; None if there isn't one."""
    found = GUIDES.get(SAME_GUIDE.get(key, key))
    if not found:
        return None
    sections = [{"title": "In this panel", "items": panel_notes(SAME_GUIDE.get(key, key))}] + found["sections"]
    return {"key": key, "title": found["title"], "lead": found["lead"], "facts": found["facts"], "sections": [s for s in sections if s["items"]],
            "faq": found["faq"], "sources": found["sources"]}
