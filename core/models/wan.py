"""Wan (2.1, 2.2): clips of 3 to 5 seconds, 5 by default (pipelines/video/wan_prompt.py writes its prompts)."""
from core.models.kinds import Family, VideoModel

FAMILY = Family("Wan", "video", encoders=("wan",), names=("wan", "wan2", "wan21", "wan22", "wan2 1", "wan2 2"))
VIDEO_MODELS = {
    "wan": VideoModel(clip_seconds=(3, 5, 5)),
}
