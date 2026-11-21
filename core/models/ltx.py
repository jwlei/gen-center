"""LTX Video (LTX-2.3): the built-in video workflow's model. Its clips follow the planner's own lengths."""
from core.models.kinds import Family

FAMILY = Family("LTX Video", "video", encoders=("ltxv",), names=("ltx", "ltxv", "ltx2", "ltx23"), nodes=("LTXV",), lora="ltx")
# Its guide, shown from the link under the workflow picker (core/model_guide.py adds what this panel holds it to).
GUIDES = {
    "ltx23": {
        "title": "LTX-2.3",
        "lead": "Lightricks' 22B video model with sound. The distilled version used here makes a clip in 8 steps, then a 4-step second pass after a 2x upscale.",
        "facts": [
            ("Size", "Multiples of 32. Official 768x512, doubled to 1536x1024; ComfyUI's template 1280x720; 1920x1088 on a strong card."),
            ("Length", "Frames in steps of 8, plus 1 (97, 121, 241). 24 or 25 fps."),
            ("Steps", "8, then 4 after the upscale (distilled)."),
            ("CFG", "1. Negative prompts do nothing; NAG can stand in."),
            ("Sampler", "euler, with the distilled sigmas."),
            ("12 GB", "Not official (32 GB+). The Q4_K_S GGUF is 15.6 GB and offloads."),
            ("Licence", "Free under $10M yearly revenue. Above that, a licence from Lightricks."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Cinematic single-subject scenes, close-ups, faces, lighting and clear camera moves.",
                "Talking and singing, in several languages. Dancing.",
                "Portrait (9:16) is better than before.",
                "Weak at fast or chaotic motion, crowds, and readable text or logos (better than LTX-2, not reliable).",
                "Sound without speech can be weaker.",
                "Past about 20 s, community reports sound glitches: extend in parts.",
            ]},
            {"title": "Prompting", "items": [
                "English. One flowing paragraph in the present tense, about 4 to 8 sentences.",
                "Cover: shot type, scene and light, the action in order, the people's looks, camera, sound.",
                "Every sentence needs an active verb. Show feeling by what the body does, not by a label.",
                "Spoken lines go in quotes, with language and accent. Say how the voice sounds.",
                "Use camera words: dolly, handheld tracking, pan, push in, pull back, over the shoulder, static.",
                "Name a style early: painterly, noir, analog film.",
                "Don't paste prompts written for another model.",
                "Negative: none at CFG 1. Kijai's NAG node (nag_scale 11, alpha 0.25, tau 2.5) gives a negative without raising CFG; it is experimental.",
            ]},
            {"title": "Picture to video", "items": [
                "A start picture is held at strength 0.7 in the first pass, 1.0 in the second. Lower than 1 reduces burn-in from the picture.",
                "First and last frame: use a guide at 0.7 on frame 0 and the last.",
                "Picture and audio to video makes a lip-synced clip: the audio is frozen and only the picture moves.",
                "Audio shorter than the clip is an error.",
            ]},
            {"title": "LoRAs", "items": [
                "On the full model, the distilled LoRA makes it work like the distilled one: 0.5 in ComfyUI's template, 0.8 in Lightricks' example.",
                "Other LoRAs are trained on the full model and loaded model-only, at 1.0 to start.",
                "LTX-2.5 LoRAs and files do not work on 2.3, and the other way round.",
            ]},
            {"title": "12 GB card", "items": [
                "GGUF (QuantStack): Q2_K 11.6 GB, Q4_K_S 15.6 GB, Q5_K_M 18.1 GB, Q8_0 23.8 GB. They offload to RAM.",
                "Text encoder: Gemma 3 12B plus ltx-2.3_text_projection (2.15 GB).",
                "Keep the first pass small (768x512), decode in tiles, and reserve VRAM.",
                "Speed on 12 GB is unmeasured.",
            ]},
        ],
        "faq": [
            ("Why must frames be 8n+1?", "That is how its video VAE counts frames. Other lengths are padded or cut."),
            ("Why do old LTX-2 files fail?", "The 2.3 VAE and upscaler changed. Use the 2.3 files (spatial upscaler x2-1.1)."),
            ("The first frame sticks to the picture.", "Lower the image strength toward 0.7."),
            ("The prompt enhancer refuses.", "It needs the abliterated Gemma LoRA, or it refuses some prompts."),
        ],
        "sources": [("ComfyUI guide", "https://docs.comfy.org/tutorials/video/ltx/ltx-2-3"), ("Model card", "https://huggingface.co/Lightricks/LTX-2.3"),
                    ("Prompting guide", "https://ltx.io/blog/prompting-guide-for-ltx-2"), ("GGUF files", "https://huggingface.co/QuantStack/LTX-2.3-GGUF")],
    },
}
