"""
The strength range worth using for each style LoRA there is, shown beside its strength box: the creator's own advice
where there is any, narrowed by what was kept from this panel's LoRA comparisons (Krea2 sets of Nov 2026, kept out of
made at 0.5 / 1 / 1.5 / 2):

  KNPV3_1_NSFW            no published advice; kept 89 / 81 / 74 / 74%: holds up to 2, best kept 1-1.5 in ordinary sets
  PornMaster_Uncensored   creator: 0.5-1; kept 89 / 81 / 59 / 48%
  realism-V2              no advice of its own (realism LoRAs for Krea 2 say 0.7-1); kept 89 / 93 / 93 / 93%
  ultra_real_v1_NSFW      0.7-0.8 (a mirror of the release); kept 96 / 88 / 42 / 8%
  ultra_real_v2_pro_SFW   UltraReal KR2_V2: 0.6-0.8; kept 96 / 65 / 8 / 4%
  Moss_ultra_real_v2_SFW  no advice found; one comparison, only 0.5 kept

Keyed by the file's name without its folder or .safetensors, lower case.
"""
import os
import re

RANGES = {
    "krea2_knpv3_1_nsfw": "0.5–1.5",
    "krea2_pornmaster_uncensored_v1_nsfw": "0.5–1",
    "krea2_realism-v2": "0.7–1.5",
    "krea2_ultra_real_v1_nsfw": "0.5–1",
    "krea2_ultra_real_v2_pro_sfw": "0.4–0.8",
    "moss_ultra_real_v2_sfw": "0.5–0.8",
}


def key(name):
    """A LoRA file's key in RANGES: "Krea2\\KNPV3.safetensors" -> "knpv3"."""
    return re.sub(r"\.safetensors$", "", os.path.basename(str(name or "").replace("\\", "/")), flags=re.I).lower()


def range_of(name):
    return RANGES.get(key(name))
