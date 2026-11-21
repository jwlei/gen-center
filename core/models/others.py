"""
Every other model family the panel recognises: only how a workflow of it is known, so it is grouped, labelled and
given its family's defaults. A family with limits, prompts or a guide of its own has a file of its own instead.

Sources: ComfyUI's CLIPLoader and DualCLIPLoader types (object_info, November 2026), docs.comfy.org/built-in-nodes/
ClipLoader, the ComfyUI changelog, and the pull requests adding FLUX.3 (#17064) and JoyImage (#14428).
"""
from core.models.kinds import Family

FAMILIES = {
    # Image
    "flux1": Family("FLUX.1", "image", ("flux",), ("flux", "flux1"), lora="flux",
                    lora_signature=r"(?:^|[._])(?:double_blocks|single_blocks|single_transformer_blocks)[._]"),
    "flux2": Family("FLUX.2", "image", ("flux2",), ("flux2", "flux 2")),
    "flux3": Family("FLUX.3", "image", ("flux3",), ("flux3", "flux 3")),
    "sdxl": Family("SDXL", "image", ("sdxl",), ("sdxl", "pony", "illustrious", "noobai"),
                   lora_signature=r"(?:^|[._])(?:input_blocks|output_blocks|middle_block|conditioner[._]embedders)[._]"),
    "sd15": Family("Stable Diffusion 1.5", "image", ("stable_diffusion",), ("sd15", "sd 1 5", "v1 5 pruned")),
    "sd3": Family("Stable Diffusion 3", "image", ("sd3",), ("sd3", "sd3 5", "sd35")),
    "chroma": Family("Chroma", "image", ("chroma",), ("chroma",)),
    "hidream": Family("HiDream", "image", ("hidream",), ("hidream",)),
    "hunyuan_image": Family("HunyuanImage", "image", ("hunyuan_image",), ("hunyuan image", "hunyuanimage")),
    "lumina2": Family("Lumina 2", "image", ("lumina2",), ("lumina", "lumina2", "neta")),
    "z_image": Family("Z-Image", "image", (), ("z image", "zimage")),
    "omnigen2": Family("OmniGen2", "image", ("omnigen2",), ("omnigen2", "omnigen")),
    "longcat_image": Family("LongCat-Image", "image", ("longcat_image",), ("longcat",)),
    "joyimage": Family("JoyImage", "image", ("joyimage",), ("joyimage", "joy image")),
    "ideogram4": Family("Ideogram 4", "image", ("ideogram4",), ("ideogram",)),
    "lens": Family("Microsoft Lens", "image", ("lens",)),
    "pixart": Family("PixArt", "image", ("pixart",), ("pixart",)),
    "pixeldit": Family("PixelDiT", "image", ("pixeldit",), ("pixeldit",)),
    "kandinsky5_image": Family("Kandinsky 5 Image", "image", ("kandinsky5_image",), ("kandinsky5 image", "kandinsky 5 image")),
    "stable_cascade": Family("Stable Cascade", "image", ("stable_cascade",), ("stable cascade",)),
    # Video, or both
    "hunyuan_video": Family("HunyuanVideo", "video", ("hunyuan_video", "hunyuan_video_15"), ("hunyuan video", "hunyuanvideo")),
    "kandinsky5": Family("Kandinsky 5 Video", "video", ("kandinsky5",), ("kandinsky5", "kandinsky 5")),
    "cosmos": Family("Cosmos", "both", ("cosmos",), ("cosmos",)),
    "mochi": Family("Mochi", "video", ("mochi",), ("mochi",)),
    "cogvideox": Family("CogVideoX", "video", ("cogvideox",), ("cogvideox", "cogvideo")),
    # Sound
    "ace": Family("ACE-Step", "audio", ("ace",), ("ace step", "acestep")),
    "stable_audio": Family("Stable Audio", "audio", ("stable_audio",), ("stable audio",)),
}
