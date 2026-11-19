"""
How different the prompts an LLM writes are from each other: the images of a set, or the clips of a film.

Variety says how far they stray: slight (one shoot, small changes), mixed (the same subject, its own picture each
time) or wide (clearly different ideas). The chips say what changes and what stays: each is left to the writer, or
set to vary, or to keep. The Generate form sends them as variety and chip_<name>; the pipelines get them as
--variety, --vary and --keep, and the writer one paragraph saying so.
"""
VARIETIES = ("slight", "mixed", "wide")
DEFAULT = "mixed"
# Each chip: its name in the form and the flags, and what the writer is told it is. In the order they're shown: those
# most used first (MOST_USED), then the rest.
CHIPS = (
    ("pose", "pose"),
    ("framing", "framing"),
    ("outfit", "outfit"),
    ("location", "setting"),
    ("subject", "subject"),
    ("hair", "hair"),
    ("action", "action"),
    ("lighting", "lighting"),
    ("colour", "colour palette"),
    ("camera", "camera angle"),
    ("style", "style"),
)
# The chips set most often (from the sets made so far), the first group on the page.
MOST_USED = ("pose", "framing", "outfit", "location", "subject", "hair", "action")
NAMES = tuple(name for name, _ in CHIPS)
WORDS = dict(CHIPS)
# What a chip says on the page, where that's shorter than what the writer is told.
SHORT = {"colour": "colour"}


def chip_labels():
    """(name, what its chip says) for each chip, in order."""
    return tuple((name, SHORT.get(name, words)) for name, words in CHIPS)


def chip_groups():
    """The chips as the page groups them: (heading, ((name, what its chip says), ...)), the most used first."""
    labels = chip_labels()
    return (("Most used", tuple(chip for chip in labels if chip[0] in MOST_USED)),
            ("More", tuple(chip for chip in labels if chip[0] not in MOST_USED)))


# The Variety hint on the page: what each level and each chip changes in the prompts the writer makes.
LEVELS = (
    ("Slight", "one shoot: the same subject, outfit, setting and light, with small changes from one to the next."),
    ("Mixed", "the same subject, each a picture of its own: the writer changes what fits."),
    ("Wide", "clearly different ideas on the brief, each one its own."),
)
EFFECTS = {
    "subject": "who or what it's of. Kept: the same person or character, described the same way each time.",
    "pose": "how the body is placed: standing, sitting, leaning, turned away.",
    "action": "what they're doing: walking, reaching, laughing. In a film, what happens in each clip.",
    "expression": "the face: smiling, serious, surprised.",
    "hair": "hairstyle and hair colour.",
    "outfit": "clothes and accessories.",
    "location": "where it is: the place and what's in the background.",
    "lighting": "the light: soft, hard, golden hour, neon, studio.",
    "colour": "the colour palette of the whole picture: warm, cool, muted, vivid.",
    "time": "day, dusk, night.",
    "camera": "where the camera is: eye level, from above, from below.",
    "framing": "how much is in the picture: close-up, half body, full body, wide.",
    "style": "the look: photo, film still, painting, illustration.",
}


def chip_hints():
    """(what its chip says, what it changes) for each chip, in order."""
    return tuple((label, EFFECTS[name]) for name, label in chip_labels())
VARY, KEEP = "vary", "keep"


def flags_from_form(form):
    """(the pipeline's flags, None) or (None, the problem) from the form's variety and chip_<name> fields."""
    variety = form.get("variety") or DEFAULT
    if variety not in VARIETIES:
        return None, "Unknown variety."
    vary, keep = [], []
    for name in NAMES:
        choice = form.get(f"chip_{name}") or ""
        if choice == VARY:
            vary.append(name)
        elif choice == KEEP:
            keep.append(name)
        elif choice:
            return None, f"Unknown choice for {WORDS[name]}."
    flags = ["--variety", variety]
    if vary:
        flags += ["--vary", ",".join(vary)]
    if keep:
        flags += ["--keep", ",".join(keep)]
    return flags, None


def parse_names(text):
    """The chips in --vary or --keep, checked: 'pose,lighting' as ['pose', 'lighting']."""
    names = [name.strip() for name in (text or "").split(",") if name.strip()]
    unknown = [name for name in names if name not in NAMES]
    if unknown:
        raise ValueError(f"Unknown: {', '.join(unknown)}. Choose from {', '.join(NAMES)}.")
    return names


def _listed(names):
    words = [WORDS[name] for name in names]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _chips(vary, keep, things):
    lines = []
    if keep:
        lines.append(f"Keep the {_listed(keep)} the same in every one of the {things}, described in the same words in each.")
    if vary:
        lines.append(f"Make the {_listed(vary)} differ from one to the next.")
    return " ".join(lines)


def image_rule(count, variety=DEFAULT, vary=(), keep=()):
    """The writer's paragraph on how a set's {count} images differ. Nothing for one image."""
    if count < 2:
        return ""
    things = f"{count} images"
    if variety == "slight":
        change = f"only the {_listed(vary)}, a little" if vary else "only small things, such as the pose, the expression or the camera angle"
        rule = f"""The {count} are one shoot: the same subject, outfit, setting, light and style, described in the same words
    in each, so they read as a series. From one to the next, change {change}: someone looking through them should see
    the same scene, caught at different moments."""
    elif variety == "wide":
        rule = f"""Every one of the {count} has to be clearly different from all the others: someone looking through them
    should never think two are the same idea. Spread them widely instead of making small changes around one idea, and
    don't let them drift off the brief to get there."""
    else:
        rule = f"""Keep the brief's subject the same in all {count}, described in the same words in each, and make each one
    clearly different from the others as a picture: its own setting, pose, light or framing, so that no two look like
    the same shot."""
    # Slight already says what changes.
    chips = _chips(() if variety == "slight" else vary, keep, things)
    return f"""

    {rule}{' ' + chips if chips else ''}"""


def variations_rule(count, seconds):
    """What a video model's writer is told when the clips are variations of one clip, not a film."""
    return f"""These are {count} variations of one {seconds}-second clip, not a film. Each is rendered on its own and
    saved as a video of its own: none comes before or after another, so none continues, answers or refers to another.
    Each is a complete take on the whole brief, and no two are the same take."""


def film_rule(variety=DEFAULT, vary=(), keep=()):
    """The writer's paragraph on how variations of a clip differ from each other (only variations get one)."""
    if variety == "slight":
        change = f"only the {_listed(vary)}, a little" if vary else "only what the action needs"
        rule = f"""Keep the clips close together: the same subject, outfit, setting, light and style throughout,
    described in the same words in each clip. From one clip to the next, change {change}."""
    elif variety == "wide":
        rule = """Make the clips clearly different from each other: each its own setting, light or angle on the brief, so
    that no two clips look like the same shot, while the subject stays recognisably the same."""
    else:
        rule = """Keep the subject the same throughout, described in the same words in each clip, and give each clip its
    own action, framing or camera move, so that no two look like the same shot."""
    chips = _chips(() if variety == "slight" else vary, keep, "clips")
    return f"""

    How much the clips differ: {rule}{' ' + chips if chips else ''}"""
