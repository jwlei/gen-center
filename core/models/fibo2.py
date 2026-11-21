"""
Fibo 2.0 (Bria), edit turbo: trained at about 1 megapixel, every size within 10% of it. Above that the coordinates it
was trained on run out from the top left corner, so the prompt leaks into that corner and it stops following it. Its
prompts are long JSON captions, written in pipelines/image/fibo2_prompt.py: one reply holds at most 30 of them.

Sources: ComfyUI's Fibo 2.0 template notes, its TextEncodeFibo2 node, huggingface.co/briaai/Fibo-2.0-edit-turbo.
"""
from core.models.kinds import Family, ImageModel

FAMILY = Family("Fibo 2.0", "image", encoders=("fibo2",), names=("fibo", "fibo2"), nodes=("TextEncodeFibo",), lora="fibo",
                lora_signature=r"(?:^|[._])(?:perceiver[._]|layers[._]\d+[._]cross_attention[._]to_kv)")
IMAGE_MODELS = {
    "fibo2": ImageModel("Fibo 2.0", most_megapixels=1.1, most_written=30, node="TextEncodeFibo2", encoder="fibo2"),
}
# Its guide, shown from the link under the workflow picker (core/model_guide.py adds what this panel holds it to).
GUIDES = {
    "fibo2": {
        "title": "Fibo 2.0 Edit Turbo",
        "lead": "Bria's 8B editing model. Edits one picture precisely and leaves the rest as it was. Edit only: it does not make a picture from text.",
        "facts": [
            ("Size", "About 1 MP, in multiples of 16. Stay within 10% of it."),
            ("Steps", "4"),
            ("CFG", "1. A negative prompt does nothing."),
            ("Sampler", "euler, simple"),
            ("References", "Up to 4 are documented, as <image_1>, <image_2>..."),
            ("12 GB", "Fits: 8.4 GB model, 4.9 GB text encoder (int8)."),
            ("Licence", "CC BY-NC 4.0: non-commercial. Selling work needs a deal with Bria."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Precise, repeatable edits that keep everything you didn't mention.",
                "Following long structured prompts: counts, positions, attributes.",
                "Text, texture and anatomy are better than Fibo 1.",
                "Weak above about 1 MP: ComfyUI's note says it stops following the prompt, and what you wrote leaks into the top left corner.",
                "Weak at text to picture. Bria points to Fibo 2.0 Dev for that.",
            ]},
            {"title": "Size", "items": [
                "Trained at about 1 MP. 1024x1024, 1424x800 and 1248x832 are the kinds of size it knows.",
                "With one reference, the picture is scaled and centre-cropped to the size it makes. Make that size the source's own to keep every pixel.",
                "With several, each is brought to its own trained size.",
            ]},
            {"title": "Prompting", "items": [
                "English only.",
                "Plain instructions work. Its own language is a long JSON caption (Bria's VGL): short_description, background_setting, style_medium, lighting, objects, text_render.",
                "For an edit, describe the finished state of the part you change, then stop.",
                "Don't write \"keep X unchanged\": ComfyUI's note says it makes the model redraw the whole frame and invent props.",
                "Name the pictures in order: \"dress the person in <image_1> in the dress from <image_2>\".",
            ]},
            {"title": "LoRAs", "items": [
                "Turbo is not meant for fine-tuning: Bria says to train on Dev.",
                "Whether a LoRA made on Dev works on Turbo is unverified.",
            ]},
            {"title": "12 GB card", "items": [
                "int8 model 8.41 GB (bf16 16.45 GB), int8 text encoder 4.86 GB (bf16 8.88 GB). No fp8, nvfp4 or GGUF from Comfy.",
                "With offload to RAM it should fit; that is inferred, not stated by Bria.",
            ]},
        ],
        "faq": [
            ("The edit ignores my prompt.", "Check the size first. Past about 1 MP it stops following the prompt."),
            ("It redrew the whole picture.", "Remove \"keep the rest unchanged\". Describe only what the region becomes."),
            ("Can it make a picture from text?", "Not this one: it is distilled for editing. Bria's Fibo 2.0 Dev does text to picture."),
            ("Does a negative prompt help?", "No. At CFG 1 it is not used."),
        ],
        "sources": [("Model card", "https://huggingface.co/briaai/Fibo-2.0-edit-turbo"), ("ComfyUI files", "https://huggingface.co/Comfy-Org/Fibo-2.0"),
                    ("VGL prompt language", "https://docs.bria.ai/vgl")],
    },
}
