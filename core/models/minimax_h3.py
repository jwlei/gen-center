"""
MiniMax H3: video, and MiniMax H3 Image, one checkpoint that makes and edits images.

    Image: 6 steps without CFG. Works from about 4 to 20 megapixels, best at about 16 (where the form starts), and
        poorly below 4. Its prompt enhancer, a small LLM in the workflow, rewrites the prompt into a long caption first,
        and calls the images it's given <Picture 1>, <Picture 2>...
    Video: clips of 5 to 15 seconds, 10 by default; 960x544 (0.52 megapixels) is the most this card makes in a
        sensible time.

Sources: ComfyUI's MiniMax H3 templates and their notes.
"""
from core.models.kinds import Family, ImageModel, VideoModel

FAMILY = Family("MiniMax H3", "both", encoders=("minimax",), names=("minimax", "h3"), nodes=("MiniMaxH3", "MinimaxH3", "H3"),
                lora="minimax_h3", lora_signature=r"(?:^|[._])token_refiner[._]")
IMAGE_MODELS = {
    "minimax_h3_image": ImageModel("MiniMax H3 Image", most_megapixels=20, default_megapixels=16, least_megapixels=4,
                                   make_or_edit_node="MiniMaxH3ImageConditioning"),
    "minimax_h3_image_edit": ImageModel("MiniMax H3 Image (edit)", same_as="minimax_h3_image", most_megapixels=20, default_megapixels=16,
                                        least_megapixels=4, image_name="<Picture {}>"),
}
VIDEO_MODELS = {
    "minimax_h3": VideoModel(most_pixels=960 * 544, clip_seconds=(5, 15, 10)),
}
# Its guide, shown from the link under the workflow picker (core/model_guide.py adds what this panel holds it to).
GUIDES = {
    "minimax_h3_image": {
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
    "minimax_h3_video": {
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
}
