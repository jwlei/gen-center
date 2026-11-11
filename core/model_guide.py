"""
A short guide to each diffusion model the workflows run, for the link under the workflow picker: what it is good and
bad at, which sizes and steps suit it, how to prompt it, its LoRAs, what fits a 12 GB card, and its licence. Written
for a phone: short lines under headings that fold.

Each guide is {title, lead, facts: [(what, value)], sections: [{title, items}], faq: [(question, answer)], sources:
[(name, url)]}. panel_notes() adds what this panel itself holds the model to (pipelines/image/models.py and
pipelines/video/media.py), so the guide and the limits it describes can't drift apart.

Facts are from the model cards, ComfyUI's docs and workflow templates (read November 2026). What could not be
confirmed is said so ("unverified"). Licences are summarised, not quoted: read them before selling what is made.
"""
import json

from core import saved_workflows as sw

FIBO2, KREA2, MOSS, QWEN_EDIT = "fibo2", "krea2", "moss_image", "qwen_image_edit"
QWEN21, H3_IMAGE, H3_VIDEO, LTX23 = "qwen_image_21", "minimax_h3_image", "minimax_h3_video", "ltx23"
# What a workflow's model is called by pipelines/image/models.py, where its guide is another one's: the edit side of a
# model that makes and edits is the same model.
SAME_GUIDE = {"qwen_image_21_edit": QWEN21, "minimax_h3_image_edit": H3_IMAGE}
# The built-in workflows, which the form lists without a saved copy in ComfyUI.
BUILT_IN = {"video": LTX23, "shorts": LTX23}

GUIDES = {
    FIBO2: {
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
    KREA2: {
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
    H3_IMAGE: {
        "title": "MiniMax H3 Image",
        "lead": "MiniMax's 33B picture model, one checkpoint that makes and edits. Made for big, detailed pictures: it does poorly small.",
        "facts": [
            ("Size", "4 to 20 MP, best near 16 MP, in multiples of 32."),
            ("Steps", "6"),
            ("CFG", "1. No negative prompt."),
            ("Sampler", "euler, simple"),
            ("References", "Up to 16, as <Picture 1>, <Picture 2>... Picture 1 is the one edited."),
            ("12 GB", "Heavy offload: 21 GB model and a 15 to 27 GB text encoder."),
            ("Licence", "MiniMax community licence: over $1M yearly revenue needs MiniMax's permission."),
        ],
        "sections": [
            {"title": "Good at, and not", "items": [
                "Fine detail and realism at large sizes. Follows instructions closely.",
                "Weak below 4 MP. Both ComfyUI templates say so.",
                "Slow on a 12 GB card: the model and its text encoder are both large.",
            ]},
            {"title": "Size", "items": [
                "Any width and height in multiples of 32.",
                "About 16 MP: 4096x4096 (1:1), 4736x3552 (4:3), 5024x3360 (3:2), 5472x3072 (16:9), 6272x2688 (21:9).",
                "ComfyUI's template starts at 4 MP so it doesn't run out of memory. Raise it if the card has room.",
                "Edit: the source is first scaled up to 4 MP. If it runs out of memory, lower the megapixels of the template's Resize node.",
            ]},
            {"title": "Prompting", "items": [
                "It wants a detailed English caption of the whole picture, up to 4096 tokens.",
                "The prompt enhancer (a small LLM in the workflow) writes that caption from a short idea. Off for text to picture, on for edits in ComfyUI's templates.",
                "No negative prompt: put what to avoid in the positive prompt.",
                "Edit: a short instruction gets \"Edit <Picture 1>.\" put in front for you.",
            ]},
            {"title": "LoRAs", "items": [
                "It is already distilled to 6 steps. No official LoRA or speed LoRA found.",
            ]},
            {"title": "12 GB card", "items": [
                "Model int8 21 GB (w4a8 12.6 GB, bf16 40 GB). Text encoder int8 27 GB, nvfp4 15.7 GB. Enhancer 7.3 GB.",
                "Expect a lot of offload to RAM. The w4a8 model is in the repo but untested here.",
                "Needs a recent ComfyUI (0.45 or later).",
            ]},
        ],
        "faq": [
            ("Why do small pictures look poor?", "It was made for 4 MP and up. Go bigger, then scale down."),
            ("Can I use a negative prompt?", "No. The official service rejects other steps and CFG, and has no negative."),
            ("Which prompt enhancer is it?", "ComfyUI's template uses a 9B model. MiniMax's own is bigger (27B)."),
        ],
        "sources": [("ComfyUI guide", "https://docs.comfy.org/tutorials/image/minimax/minimax-h3-image"), ("Model card", "https://huggingface.co/MiniMaxAI/MiniMax-H3-Image"),
                    ("ComfyUI files", "https://huggingface.co/Comfy-Org/MiniMax-H3-Image")],
    },
    MOSS: {
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
    QWEN21: {
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
    QWEN_EDIT: {
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
    H3_VIDEO: {
        "title": "MiniMax H3 (video)",
        "lead": "MiniMax's open video model with sound: voice, effects and music in one pass. It reads text, pictures, video and audio.",
        "facts": [
            ("Size", "About 1 MP: 1344x768 is its 768p. Multiples of 32."),
            ("Length", "About 5 to 15 s at 24 fps. Frames in steps of 17, plus 5."),
            ("Steps", "20 (full), or 4 to 8 with a turbo LoRA."),
            ("CFG", "1. No negative prompt."),
            ("Sampler", "res_multistep, simple. beta can be better with references."),
            ("References", "Up to 9 pictures, 3 videos, 3 audio clips; 12 files in all."),
            ("12 GB", "Possible only with heavy RAM offload. Keep it small and short."),
        ],
        "sections": [
            {"title": "Two models", "items": [
                "fl2va: text to video, picture to video, first and last frame.",
                "ref2va: reference to video. Different weights; they are not interchangeable.",
                "FastH3 (8 steps) is for drafts: text and first/last frame only, no references.",
            ]},
            {"title": "Good at, and not", "items": [
                "Following instructions that mix text, pictures, video and audio.",
                "Locking a face, style, motion, camera or voice from references.",
                "Dialogue in 11 languages and text drawn on screen.",
                "Reference to video is very sensitive to wording.",
                "With audio references it can give a line to the wrong speaker.",
                "The 4-step reference LoRA (v0.1) is faster but weaker with references and audio. Use 20 to 25 steps if they must hold.",
                "Larger than its native size is slower and adds no detail. 2K is a hosted service, not in the open weights.",
            ]},
            {"title": "Size and length", "items": [
                "608x352 (0.2 MP), 864x480 (0.4), 960x544 (0.5), 1056x608 (0.6), 1216x672 (0.8), 1280x736 (0.9), 1344x768 (about 1 MP).",
                "Length snaps up: asking for 5 s gives 124 frames.",
                "A first-frame picture is stretched to the canvas, not cropped. Match the size to its shape. The last frame is cropped.",
                "A reference video has to be 24 fps already.",
            ]},
            {"title": "Prompting", "items": [
                "English. Say it in one block: the scene, then timed shots.",
                "Fields: integrated_multimodal_description, overall_soundscape, non_diegetic_music (or N/A).",
                "Shots: [Shot 1] starts at 0.00 s. Later: [Shot 2] At 00:03.500, the camera cuts to... Never a range like [5s-8s].",
                "Camera: type, amount, speed. Push In, Pull Out, Pan, Truck, Tilt, Arc Shot, Tracking Shot, Static Shot.",
                "Speech goes in <d>[Language] words</d> exactly. Mark speakers (S1), (S2). A voiceover: \"says in an off-screen voiceover\", \"lips remain closed\".",
                "Text on screen goes in English double quotes, exactly.",
                "No negative prompt: at CFG 1 naming what you don't want brings it in. If speech you didn't ask for appears, fill both sound fields.",
                "Reference mode: say which reference drives identity, style, motion, camera or voice. <Picture 1>, <Video 1> and <Audio 1> follow the order they are connected.",
                "Audio gives the voice, not the words. Use one clip per speaker.",
                "Style LoRAs compete with references: use about 0.5.",
            ]},
            {"title": "Speed LoRAs", "items": [
                "fl2v turbo 8-step (strength 1.0). fl2v 4-step 768p. ref2v 4-step v0.1.",
                "Turbo gives slightly softer motion and sound. Raise the steps (about 25) for motion quality.",
                "Turbo step counts differ between the docs (8) and the templates (4 to 6): check the template you load.",
                "Don't put a ref2v LoRA on the fl2va model, or the other way round (inferred).",
            ]},
            {"title": "12 GB card", "items": [
                "Model int8 19.5 GB (w6a8 14.9 GB). Text encoder nvfp4 14.6 GB. Video VAE 2.6 GB.",
                "No official minimum. One user reports a 12 GB card with 96 GB of RAM and a third-party model, at 416p.",
                "Use a recent ComfyUI (0.36 or later; 0.38 for ControlNet Union 2).",
            ]},
            {"title": "Licence", "items": [
                "MiniMax's licence text allows commercial use under $20M yearly revenue in its territory, and lists the USA, EU, UK and South Korea as outside it, as read from the file. Check it before you rely on this.",
                "ComfyUI's docs say commercial use of local output needs a licence through Comfy (the only official reseller). The two disagree: ask Comfy or a lawyer.",
                "You may not use the output to train another AI model.",
            ]},
        ],
        "faq": [
            ("Why does my first frame look stretched?", "The canvas aspect doesn't match the picture. Set a size in its shape."),
            ("The soundtrack of my reference video is ignored.", "Wire its audio into ref_video_audio_N, or it doesn't count as <Audio N>."),
            ("Why is Max reference size so slow?", "ref_image_size max keeps a 2048 px short edge, and reference tokens ride through every step. match is faster."),
            ("Black frames mid-clip?", "Reported for first/last-frame runs, depending on seed and size. Try another seed."),
        ],
        "sources": [("ComfyUI guide", "https://docs.comfy.org/tutorials/video/minimax/minimax-h3"), ("Prompt guide", "https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide"),
                    ("Model card and licence", "https://huggingface.co/MiniMaxAI/MiniMax-H3"), ("ComfyUI files", "https://huggingface.co/Comfy-Org/MiniMax-H3")],
    },
    LTX23: {
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
    from pipelines.video import media
    notes = []
    if key in (LTX23, H3_VIDEO):
        if key == H3_VIDEO:
            return [f"Sizes up to 960x544 ({media.MOST_PIXELS['minimax_h3'] / 1e6:.2f} MP), which this card renders in a sensible time. Its own 768p is 1344x768."]
        return [f"Sizes up to {media.DEFAULT_SHAPE[0]}x{media.DEFAULT_SHAPE[1]} ({media.RENDER_AREA / 1e6:.2f} MP)."]
    ids = {QWEN21: ("qwen_image_21", "qwen_image_21_edit"), H3_IMAGE: ("minimax_h3_image", "minimax_h3_image_edit"),
           FIBO2: (FIBO2,), KREA2: (KREA2,), MOSS: (MOSS,), QWEN_EDIT: (QWEN_EDIT,)}.get(key, ())
    for model in ids:
        most, least = models.most_megapixels(model), models.LEAST_MEGAPIXELS.get(model)
        part = [f"up to {most:g} MP" if most else f"up to {media_max():g} MP (the form's own limit)"]
        if least:
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
