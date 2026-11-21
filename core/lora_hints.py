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
  fingering_V0.1_NSFW     creator: 0.6-0.85, no trigger word, made to stack with character LoRAs; not compared yet

Keyed by the file's name without its folder or .safetensors, lower case.
"""
import os
import re

# Each: ours (shown first, and what a strength is brought within when the LoRA is swapped), and the author's or the
# release's own, where one was found (shown under it).
RANGES = {
    "krea2_knpv3_1_nsfw": {"ours": "0.5–1.5", "author": None},
    "krea2_pornmaster_uncensored_v1_nsfw": {"ours": "0.5–1", "author": "0.5–1"},
    "krea2_realism-v2": {"ours": "0.7–1.5", "author": None},
    "krea2_ultra_real_v1_nsfw": {"ours": "0.5–1", "author": "0.7–0.8"},
    "krea2_ultra_real_v2_pro_sfw": {"ours": "0.4–0.8", "author": "0.6–0.8"},
    "moss_ultra_real_v2_sfw": {"ours": "0.5–0.8", "author": None},
    # Until a comparison says otherwise, the creator's own.
    "krea2_fingering_v0.1_nsfw": {"ours": "0.6–0.85", "author": "0.6–0.85"},
}


def key(name):
    """A LoRA file's key in RANGES: "Krea2\\KNPV3.safetensors" -> "knpv3"."""
    return re.sub(r"\.safetensors$", "", os.path.basename(str(name or "").replace("\\", "/")), flags=re.I).lower()


def range_of(name):
    """Our range for a LoRA ("0.5–1"), or None for one it doesn't know."""
    return (RANGES.get(key(name)) or {}).get("ours")


def author_range_of(name):
    """The author's own range for a LoRA, or None where none was found."""
    return (RANGES.get(key(name)) or {}).get("author")


# Which range comes first (the Settings' LoRA strength range): its author's, or what this panel's comparisons kept.
AUTHOR, TESTED = "author", "tested"


def preferred_range(name, prefer=AUTHOR):
    """The range a LoRA is held to: the one preferred, else the other; None where neither is known."""
    ranges = (author_range_of(name), range_of(name))
    return (ranges if prefer != TESTED else ranges[::-1])[0] or ranges[0] or ranges[1]


def bounds_of(name, prefer=AUTHOR):
    """
    The range a strength test of a LoRA runs over, and a strength is brought within, as (low, high): the author's
    (0.6, 0.8 for "0.6–0.8") or ours, as prefer says, else the other; None where neither is known.
    """
    found = re.split(r"[–-]", preferred_range(name, prefer) or "")
    try:
        return (float(found[0]), float(found[1])) if len(found) == 2 else None
    except ValueError:
        return None


def top_of(name, prefer=AUTHOR):
    """Where a strength test of a LoRA stops: the top of bounds_of, or None."""
    bounds = bounds_of(name, prefer)
    return bounds[1] if bounds else None
