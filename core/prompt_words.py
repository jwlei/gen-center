"""
How long a written prompt is, in words: the number on the image and video forms, and the range the LLM is asked for
around it. A bare number reads to a model as a limit to stop short of; a range is a length to aim for.
"""

SPREAD = .2
# What the forms take: an image prompt from 40 to 400 words, a clip's from 40 to 500 (H3's longest).
LEAST = 40
MOST = {"image": 400, "video": 500}
# The video form's slider starts a step below LEAST: there, it is each video model's own length.
AUTO = LEAST - 10


def word_range(words):
    """The length asked for: 20% either side of the number, to the nearest five words, as (least, most)."""
    return 5 * round(words * (1 - SPREAD) / 5), 5 * round(words * (1 + SPREAD) / 5)


def flags_from_form(form, pipeline, usual=None):
    """(["--words", n] or [], None) or (None, the problem), from the form's words field. Left out when blank or usual."""
    words = (form.get("words") or "").strip()
    if not words or (pipeline == "video" and words == str(AUTO)):
        return [], None
    if not words.isdigit() or not LEAST <= int(words) <= MOST[pipeline]:
        return None, f"Words per prompt is from {LEAST} to {MOST[pipeline]}."
    return ([] if int(words) == usual else ["--words", words]), None
