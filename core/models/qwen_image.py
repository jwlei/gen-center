"""
Qwen-Image: Qwen-Image-Edit 2511, and Qwen-Image 2.1, which makes and edits.

    Qwen-Image-Edit 2511: up to 2560x2560, starting at 1024x1024. Calls the images it's given "Picture 1"...
    Qwen-Image 2.1 Turbo: native 2K, but on this 12 GB card less. Kokon measured what fits: about 12,600 of the model's
        tokens (16 x 16 pixels each) on 12 GB, about 3.2 megapixels, which an edit shares between the image it makes and
        the one it's shown at the same size. So 3.2 to make one, half that to edit one. An edit shows the model every
        image it's given beside the one it makes, so it takes 4 at most. Its encoder labels them <image1>, <image2>...
        It can make a new picture from references (its template's Custom size), work on a part of an image marked in a
        colour, and make a transparent background when the prompt says so.

Sources: ComfyUI's Qwen-Image 2.1 template, and Kokon's planner (token_budget in github.com/GabrieleLozupone/kokon,
crates/qls-core/src/planner.rs).
"""
from core.models.kinds import Family, ImageModel

TRANSPARENT = "This is an RGBA format image with transparency. {} The image has an alpha channel and a transparent background."

FAMILY = Family("Qwen-Image", "image", encoders=("qwen_image",), names=("qwen image", "qwenimage"), nodes=("TextEncodeQwenImage",),
                lora="qwen", lora_signature=r"(?:^|[._])transformer_blocks[._]\d+[._](?:img|txt)_mlp[._]")
IMAGE_MODELS = {
    # 2560x2560, in megapixels of 1024 x 1024 pixels as the form counts them (pipelines/image/media.py).
    "qwen_image_edit": ImageModel("Qwen-Image-Edit", most_megapixels=2560 * 2560 / (1024 * 1024), default_megapixels=1, image_name="Picture {}",
                                  node="TextEncodeQwenImageEditPlus"),
    "qwen_image_21": ImageModel("Qwen-Image 2.1", most_megapixels=3.2, token_budget=3.2, transparent=TRANSPARENT,
                                make_or_edit_node="TextEncodeQwenImage21"),
    "qwen_image_21_edit": ImageModel("Qwen-Image 2.1 (edit)", same_as="qwen_image_21", most_megapixels=1.6, most_images=4, token_budget=3.2,
                                     image_name="<image{}>", compose_switch="face_custom_size", most_megapixels_compose=2.2, regions=True,
                                     transparent=TRANSPARENT),
}
# Its guide, shown from the link under the workflow picker (core/model_guide.py adds what this panel holds it to).
GUIDES = {
    "qwen_image_21": {
        "title": "Qwen-Image 2.1 Turbo",
        "lead": "Qwen's picture model: typography, posters, transparent images and multi-picture edits. Turbo is the 8-step version.",
        "facts": [
            ("Size", "Native up to 2048x2048 (4 MP). Past 2K it stops following the prompt. Multiples of 32."),
            ("Steps", "8, with a fixed set of sigmas."),
            ("CFG", "1. A negative prompt does nothing."),
            ("Sampler", "euler, simple"),
            ("References", "Up to 10, as <image1>, <image2>... Output follows image 1."),
            ("12 GB", "Fits: Q4_K_M GGUF is 4.2 GB, or int8 7.3 GB."),
            ("Licence", "Qwen Research Licence: research use. Commercial use needs a licence from Qwen."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Text in pictures and dense layouts: posters, infographics, interfaces.",
                "Transparent (RGBA) pictures.",
                "Edits that keep a person's or product's identity; edits of one region.",
                "Fine checkerboard texture can show in detailed photos. madebyollin's texture-fix VAE helps (unofficial).",
                "Slow at large sizes: ComfyUI measured 12 MP at about 6 s per step against 0.3 s at 1 MP on a fast card.",
            ]},
            {"title": "Size", "items": [
                "Official presets: 2048x2048 (1:1), 2400x1792 (4:3), 2528x1696 (3:2), 2752x1536 (16:9), and the same turned.",
                "On this 12 GB card less is held: about 3.2 MP to make one picture, half that to edit one, since the edit shows the model its picture too.",
                "Edit: resolution is a total pixel budget. 0 keeps the source's own size, rounded to 32.",
            ]},
            {"title": "Prompting", "items": [
                "English and Chinese. Put text to be drawn in quotes.",
                "Transparent: \"This is an RGBA format image with transparency. [what]. The image has an alpha channel and a transparent background.\" Save as PNG.",
                "Edit: refer to pictures as <image1>, <image2>. Example: \"Keep the character and pose in <image1> unchanged, put the shirt from <image2> on the character.\"",
                "Mark a region by painting a colour on a second picture, then name the colour in the prompt.",
                "A prompt enhancer (a 9B model) is off by default. If its thinking uses up its length, it returns nothing and the edit stays close to the source.",
            ]},
            {"title": "LoRAs", "items": [
                "Speed LoRAs for the full model: Qwen's turbo LoRA (8 steps, CFG 1), PrunaAI's 5, 6 and 8 step LoRAs, and lightx2v's unofficial Lightning (4 steps).",
                "Load them with a model-only LoRA loader. A recommended strength was not found: 1.0 is the usual.",
                "Style LoRAs: more than 160 exist for the base model.",
            ]},
            {"title": "12 GB card", "items": [
                "GGUF Q4_K_M 4.2 GB is the usual choice; Q8_0 (7.6 GB) is closest to bf16. Below 4 bits it drifts.",
                "Text encoder int8 9.4 GB or w4a8 6.3 GB. VAE 0.6 GB.",
            ]},
        ],
        "faq": [
            ("The edit came back unchanged.", "The enhancer may have returned an empty prompt, or the cache node is stale. Switch the enhancer off and try again."),
            ("Can I make 4K?", "Not well: ComfyUI says it loses the prompt. Make 2K and upscale."),
            ("Why does Turbo use odd sigmas?", "They are fitted to 8 steps at 1 MP. Other step counts need another schedule."),
            ("Do LoRAs for earlier Qwen-Image work?", "No. 2.1 changed its layers: an older LoRA loads without error and does nothing. The panel refuses them."),
        ],
        "sources": [("ComfyUI guide", "https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1"), ("Model card", "https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo"),
                    ("GGUF files", "https://huggingface.co/unsloth/Qwen-Image-2.1-Turbo-GGUF")],
    },
    "qwen_image_edit": {
        "title": "Qwen-Image-Edit 2511",
        "lead": "Qwen's 20B editing model: keeps characters consistent, fuses people, swaps materials, changes viewpoints. Apache 2.0.",
        "facts": [
            ("Size", "About 1 MP. No official size table; the edit reads each picture at about 1 MP."),
            ("Steps", "40 (CFG 4) officially; 20 in ComfyUI's template. 4 with the Lightning LoRA."),
            ("CFG", "4. With the Lightning LoRA: 1."),
            ("Sampler", "euler, simple. Shift 3.1."),
            ("References", "Up to 3: image 1, 2 and 3."),
            ("12 GB", "Needs offload: int8 is 19 GB."),
            ("Licence", "Apache 2.0: commercial use allowed."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Consistent characters, and several people in one picture.",
                "Material and product changes. New viewpoints and lighting, built in from popular LoRAs.",
                "Big for a 12 GB card, and only three pictures go in.",
            ]},
            {"title": "Prompting", "items": [
                "Plain instructions, English or Chinese.",
                "Refer to pictures as \"image 1\" and \"image 2\": \"Change the furniture leather in image 1 to the fur material in image 2.\"",
                "The negative prompt in Qwen's own code is a single space.",
            ]},
            {"title": "Turbo mode (Lightning LoRA)", "items": [
                "lightx2v's Lightning 4-step LoRA: 4 steps, CFG 1, strength 1.0. About ten times faster.",
                "Don't mix it with the 40-step, CFG 4 settings.",
                "Other 2511 LoRAs exist (multiple angles, and more). 2509 LoRAs on 2511 are unverified.",
            ]},
            {"title": "12 GB card", "items": [
                "int8 19.1 GB, bf16 38 GB. Text encoder qwen_2.5_vl_7b fp8 8.7 GB.",
                "I found no verified GGUF for 2511.",
            ]},
        ],
        "faq": [
            ("The Lightning LoRA gives mush.", "It needs CFG 1 and 4 steps. Don't leave the 40-step settings on."),
            ("What are the Edit Model Reference Method nodes?", "Only for repackaged files from other people. Comfy's own files don't need them."),
        ],
        "sources": [("ComfyUI guide", "https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511"), ("Model card", "https://huggingface.co/Qwen/Qwen-Image-Edit-2511"),
                    ("Lightning LoRA", "https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning")],
    },
}
