"""
Krea-2: makes 1K to 2K images, up to 2048x2048, in 8 steps (Turbo).

Sources: ComfyUI's Krea-2 template notes and huggingface.co/Comfy-Org/Krea-2.
"""
from core.models.kinds import Family, ImageModel

FAMILY = Family("Krea-2", "image", encoders=("krea2",), names=("krea", "krea2"), nodes=("Krea2",), lora="krea",
                lora_signature=r"(?:^|[._])txtfusion[._]")
IMAGE_MODELS = {
    "krea2": ImageModel("Krea-2", most_megapixels=4.2, encoder="krea2"),
}
# Its guide, shown from the link under the workflow picker (core/model_guide.py adds what this panel holds it to).
GUIDES = {
    "krea2": {
        "title": "Krea-2 Turbo",
        "lead": "Krea's 12B text-to-picture model, built for looks and variety. Turbo is the 8-step version for making pictures.",
        "facts": [
            ("Size", "1K to 2K: up to 2048x2048 (4.2 MP), in multiples of 16."),
            ("Steps", "8"),
            ("CFG", "1 (0 in Krea's own code). A negative prompt does nothing."),
            ("Sampler", "euler, simple"),
            ("Edit", "No. Text to picture only."),
            ("12 GB", "Offloads to RAM. The nvfp4 file (7.7 GB) is the only one that fits whole."),
            ("Licence", "Free under $1M yearly revenue. Above that, ask Krea."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Looks: aesthetics and style variety are what it was made for.",
                "Takes long, detailed prompts best. Short ones work less well.",
                "Nine official style LoRAs, made to be used at 1.0.",
                "Krea-2 Raw is the base for training. Krea says not to use it for pictures.",
            ]},
            {"title": "Prompting", "items": [
                "Natural language, long and specific.",
                "Put any text to be drawn in quotes.",
                "Krea's repo has a prompt-expansion system prompt (docs/expansion.txt). ComfyUI's template has an enhance switch, on by default.",
                "No negative prompt: say what you want, not what to avoid.",
            ]},
            {"title": "Style LoRAs", "items": [
                "Say the trigger phrase in the prompt, with the LoRA at 1.0 (0.8 to 1.0 works).",
                "darkbrush: monochrome ink wash style.",
                "dotmatrix: monochrome stippling style.",
                "kidsdrawing: naive expressive sketch style.",
                "neondrip: textured abstract style.",
                "rainywindow: rainy window style.",
                "retroanime: purple retro anime style.",
                "softwatercolor: art deco watercolor style.",
                "sunsetblur: ethereal motion blur style.",
                "vintagetarot: vintage tarot style.",
                "Train a LoRA on Raw and run it on Turbo: it carries over.",
            ]},
            {"title": "12 GB card", "items": [
                "Turbo files: nvfp4 7.67 GB, fp8 12.9 GB, int8 13.5 GB, bf16 26.3 GB. Text encoder 4.9 to 5.2 GB.",
                "Anything bigger than the card offloads to RAM. Speed-up from nvfp4 is probably for RTX 50 cards only (unverified).",
            ]},
        ],
        "faq": [
            ("Why is my prompt changed?", "The template's prompt enhancer is on by default. Turn it off to send your words as they are."),
            ("Can I go above 2K?", "It is made for 1K to 2K. Bigger is not what it was trained on."),
            ("Where is the negative prompt?", "There is none: CFG 1 skips it."),
        ],
        "sources": [("Krea-2 on ComfyUI docs", "https://docs.comfy.org/tutorials/image/krea/krea-2"), ("Turbo model card", "https://huggingface.co/krea/Krea-2-Turbo"),
                    ("Files and LoRAs", "https://huggingface.co/Comfy-Org/Krea-2"), ("Prompting guide", "https://github.com/krea-ai/krea-2/blob/main/docs/prompting.md")],
    },
}
