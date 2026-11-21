"""MOSS Image: 0.25 to 4.2 megapixels here (about 2K x 2K), starting at 2."""
from core.models.kinds import Family, ImageModel

FAMILY = Family("MOSS Image", "image", encoders=("moss_image",), names=("moss",), lora="moss",
                lora_signature=r"(?:^|[._])layers[._]\d+[._]proj[._](?:qkv|ffn_down|ffn_up_gate)(?:[._]|$)")
IMAGE_MODELS = {
    "moss_image": ImageModel("MOSS Image", most_megapixels=4.2, default_megapixels=2, encoder="moss_image"),
}
# Its guide, shown from the link under the workflow picker (core/model_guide.py adds what this panel holds it to).
GUIDES = {
    "moss_image": {
        "title": "MOSS-Image",
        "lead": "OpenMOSS's 5B picture model. Strong at text in pictures (Chinese and English), layouts and long prompts. Light enough for 12 GB.",
        "facts": [
            ("Size", "1 to 2 MP best. Works from 0.25 MP up to 4 MP (2K). Multiples of 16."),
            ("Steps", "25 in ComfyUI's template; 50 in the official guide."),
            ("CFG", "2.5 in the template; 3 to 6 officially."),
            ("Sampler", "er_sde, simple (euler officially). Shift 5."),
            ("Edit", "Only with the edit LoRA, up to 4 references."),
            ("12 GB", "Fits: 5.4 GB model, 7.3 GB text encoder."),
            ("Licence", "Apache 2.0."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Text drawn in the picture, with its own layout. Chinese and English.",
                "Long prompts (about 4K tokens), tags, or a JSON layout with boxes for text and objects.",
                "Anime and photoreal both.",
                "Line breaks in text may not fall where you want: put \\n in the prompt.",
                "Layout control is experimental.",
            ]},
            {"title": "Prompting", "items": [
                "English has the most training data; Chinese works well.",
                "Tag prompts go in this order: quality, score, meta, year, character, series, artist, general.",
                "Negative prompt works (CFG above 1). The guide suggests: nsfw, worst quality, bad anatomy, watermark, jpeg artifact.",
                "Skip Layer Guidance on layer 22 helps detail. Switching it off looks more real but can collapse details.",
            ]},
            {"title": "Editing", "items": [
                "Editing is a LoRA (moss_image_edit_lora_rank_64, about 0.3 GB) on the Base or SFT model.",
                "Up to 4 references. Say what each is for.",
                "Trained phrasing: \"Change only the X to Y. Keep the character, face, hair, pose, background and composition unchanged.\"",
                "Use the template's settings: 30 steps, CFG 4. A lower CFG lets stray things in.",
                "References enter at the size they arrive: scale them to about 1 MP first.",
            ]},
            {"title": "LoRAs", "items": [
                "Train on Base, not SFT. Keep the text encoder frozen.",
                "A colour and depth control LoRA also exists.",
            ]},
        ],
        "faq": [
            ("Which shift node?", "ModelSamplingAuraFlow. Not ModelSamplingSD3."),
            ("Which loader type?", "CLIPLoader type moss_image. It needs a ComfyUI from mid-October 2026 or later."),
            ("Why are the template's steps lower than the guide's?", "Kijai's faster settings: 25 steps, CFG 2.5, er_sde. Use 50 steps and CFG 3 to match the official look."),
        ],
        "sources": [("User guide", "https://github.com/OpenMOSS/MOSS-Image/blob/main/USERGUIDE.md"), ("ComfyUI notes", "https://github.com/OpenMOSS/MOSS-Image/blob/main/comfyui/README.md"),
                    ("ComfyUI files", "https://huggingface.co/Comfy-Org/MOSS-Image"), ("Edit LoRA", "https://huggingface.co/chinoll/Moss-Image-Edit")],
    },
}
