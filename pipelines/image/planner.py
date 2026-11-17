import math

from pydantic import BaseModel, ValidationError

from core import explicit as explicit_rules, prompt_words, variety as variety_rules
from core.llm_reply import CutOff
from pipelines.image import fibo2_prompt, models
from pipelines.video import planner as llm

PROMPT_ATTEMPTS = 3
# A set's most images: 50 with your prompt as it is, 30 written by an LLM. Their prompts come from one request of up
# to round_size(words), else in even rounds (write_prompts).
MAX_IMAGES = 50
MAX_WRITTEN = 30
ROUND_SIZE = 20
# How long each new or composed picture's prompt is, in words (the form's number): the workflows' own prompt enhancers
# write about 150-250, and the suggested range is where the image models use what they are told. Edit instructions
# keep their own 20-60, and Fibo 2.0's captions their own shape.
WORDS = 200
LEAST_WORDS, MOST_WORDS = prompt_words.LEAST, prompt_words.MOST["image"]
SUGGESTED_WORDS = (120, 250)
# Tokens, for sizing the rounds and the estimate: English prose is about 1.35 tokens a word to these models, each
# version's title and JSON about 20 more, an attached image about 280, and the instructions about 4 characters a token.
TOKENS_PER_WORD = 1.35
VERSION_TOKENS = 20
IMAGE_TOKENS = 280
CHARS_PER_TOKEN = 4
# One round's reply is kept to this many tokens, its longest prompts counted: two thirds of the local model's 12,288
# (core.h3_refiner.PLAN_TOKENS), as one that runs long still fits. 30 at once at 200 words did not.
ROUND_TOKENS = 8000


class Version(BaseModel):
    title: str
    prompt: str


class Versions(BaseModel):
    title: str
    versions: list[Version]


# The local model's structured output: every object closed and every field required.
VERSIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "versions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "prompt": {"type": "string"}},
                "required": ["title", "prompt"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "versions"],
    "additionalProperties": False,
}


def _names(images, model):
    """How the prompts refer to the attached images, when there's more than one."""
    if images < 2:
        return ""
    first, second = models.image_name(model, 1), models.image_name(model, 2)
    return f"""
    - You have been given {images} images. The model knows them as {first}, {second} and so on, in the order they are
      attached, so call them that whenever you refer to one."""


def _edit_rules(images, model=None):
    """
    The model gets the image and this instruction, and redraws the image following it. What Kokon's blind A/B tests on
    Qwen-Image settled (enhancer.rs there): lead with the operation, describe only what changes, and end on one clause
    keeping the rest. Describing what stays makes the model draw it again; an example in the instructions turns up in
    the prompts, so there are none.
    """
    return f"""
    An AI image editing model ({models.label(model) if model else "an image editor"}) will edit the attached image
    once per prompt. It sees the image and that prompt, and knows nothing about the others. Look at the image closely
    first: who or what is in it, the pose, the framing, the setting, the light, the medium.

    Each prompt is an instruction to edit that image:
    - Start with the operation: Change, Replace, Remove, Add or Turn. Then say exactly what changes, where it is, and
      what it becomes, plainly and specifically: name its colours, materials, shapes, sizes and textures.
    - Describe only what changes. Never describe what stays: the model redraws whatever a prompt describes.
    - Keep the same person, with the same face and identity, unless the brief asks otherwise; a change to someone
      never makes them someone else.
    - End with exactly one sentence keeping the rest: "Keep everything else in the image unchanged." For a change to
      the whole picture's style, light or mood, end with "Keep the composition and the subjects unchanged." instead.
    - Copy anything the brief fixes exactly: words to show, in double quotes, counts and colours.
    - One short paragraph, 20-60 words, up to about 120 for several changes at once. No lists, no labels, no
      markdown.{_names(images, model)}"""


# The LLM is asked for a range around the number given (core.prompt_words).
WORD_SPREAD = prompt_words.SPREAD
word_range = prompt_words.word_range


def _word_range(words):
    least, most = word_range(words)
    return f"{least}-{most} words"


def prompt_tokens(words, longest=False):
    """One version's tokens in the reply: its prompt at {words} (or at the top of its range), its title and JSON."""
    return round(words * (1 + WORD_SPREAD if longest else 1) * TOKENS_PER_WORD + VERSION_TOKENS)


# An edit instruction's length (_edit_rules: 20-60 words), whatever the slider says.
EDIT_WORDS = 40


def _words(words, images, compose, model):
    """How long the prompts written will be: the slider's, except for edit instructions, which keep their own."""
    return EDIT_WORDS if images and not compose and model != models.FIBO2 else words


def round_size(words=WORDS):
    """How many prompts one request writes: up to ROUND_SIZE, fewer as they get longer."""
    return max(1, min(ROUND_SIZE, ROUND_TOKENS // prompt_tokens(words, longest=True)))


def _compose_rules(images, model=None, words=WORDS):
    """
    The images are references for a new picture, not one to edit: as Kokon's compose. Never asking to keep a
    reference unchanged, which turns the new picture into an edit of image 1.
    """
    names = ", ".join(models.image_name(model, number) for number in range(1, images + 1))
    return f"""
    An AI image model ({models.label(model) if model else "an image model"}) will make a new picture once per prompt,
    using the attached images as references: {names}. It sees them and that prompt, and knows nothing about the
    others. Look at each image closely first, and decide what the brief wants from it: a person's face and look, a
    product with its shape, colours and markings, a place, a style.

    Each prompt describes the new picture:
    - Say what is taken from each image, calling it {models.image_name(model, 1)}, {models.image_name(model, 2)} and so on,
      then describe the new scene around it: what happens, the setting, the composition and camera view, the medium
      and the light.
    - Never ask to keep an image unchanged or as it is: the picture is a new one, and only borrows from them.
    - Everyone in an image is an adult, and looks it.
    - Copy anything the brief fixes exactly: words to show, in double quotes, counts and colours.
    - One paragraph of plain prose, {_word_range(words)}, each as full as if it were the only one. No lists, no labels,
      no markdown."""


def _create_rules(model=None, words=WORDS):
    """
    The rules for a new image from text: the medium early, the light always, fixed content copied word for word. The
    checklist and length follow the workflows' own prompt enhancers, which write one prompt at a time: asked for many,
    a model writes each shorter unless told every one is as full as a single one.
    """
    return f"""
    An AI image model ({models.label(model) if model else "an image model"}) will make one image per prompt. It sees
    only that prompt, and knows nothing about the others, so each has to say everything about how its image looks.
    Everyone in an image is an adult, and looks it.

    Each prompt describes one finished image, as fully as if it were the only prompt you were writing: writing many
    is no reason to make any of them shorter. Name the medium early: a photograph, a painting, an illustration, a
    render. If the brief names one, use that. Then cover, concretely:
    - Each person: their age and ethnicity first, then body and proportions, face, skin texture, expression and
      where they look, hair and its colour, jewellery and accessories, and clothing with its materials and fit.
    - The pose: posture, what the hands do, and how people in the image touch and relate to each other.
    - The framing and camera: close-up, medium or full body, the camera angle, and where the subject sits in the frame.
    - The setting: indoors or out, the background with its colours, objects and textures, and the depth of field.
    - The light: its direction, softness and contrast, and the time of day or the lamps it comes from.
    - The look: the style, the lens (wide, portrait compression, bokeh), sharpness and grain, the dominant colours and
      the colour grading.
    Keep each thing's details next to it. If several images share a subject, describe it in the same words in each,
    or they won't look alike.
    - No text in the image: no letters, captions, signs, logos or watermarks, unless the brief gives the exact words,
      in which case copy them exactly, in double quotes.
    - Copy anything else the brief fixes exactly, such as counts and colours.
    - No quality tags, sizes or negative prompts.
    - One dense paragraph of plain prose, {_word_range(words)}. No lists, no labels, no markdown."""


TRANSPARENT_RULE = """

    The images are made with a transparent background, to be cut out and placed on others: describe only the subject,
    whole and in view, with no background, floor, frame or scenery around it."""


def _instructions(brief, count, images, model=None, compose=False, transparent=False, variety=variety_rules.DEFAULT,
                  vary=(), keep=(), words=WORDS):
    """
    How to write the prompts, for editing what's attached, making a new picture from it, or making one from nothing.
    variety, vary and keep: how different the {count} are, and what changes or stays (core.variety). words: how long
    each new or composed picture's prompt is.
    """
    versions = "one image" if count == 1 else f"{count} different versions"
    apart = variety_rules.image_rule(count, variety, vary, keep)
    if model == models.FIBO2:
        rules = fibo2_prompt.rules(images)
    elif images and compose:
        rules = _compose_rules(images, model, words)
    elif images:
        rules = _edit_rules(images, model)
    else:
        rules = _create_rules(model, words)
    return f"""
    You are writing the prompts for {versions} from this brief, in the words of the person making them: "{brief}"

    The brief is short on purpose. Invent the detail, in keeping with it and never contradicting it.{apart}
    {rules}{TRANSPARENT_RULE if transparent else ""}

    Return a title for the set, 2-5 words, and exactly {count} {"version" if count == 1 else "versions"}. For each:
    - title: 2-5 words saying what sets this one apart.
    - prompt: the text the model gets, following the rules above."""


def _tidy(model, has_images):
    """How a prompt goes to this model. Fibo 2.0's are JSON captions: one that isn't the caption asked for comes back empty."""
    return (lambda prompt: fibo2_prompt.tidy(prompt, has_images)) if model == models.FIBO2 else str.strip


def _usable(versions, tidy):
    """The versions with a prompt the model can use, each prompt once, as [{title, prompt}]."""
    seen, usable = set(), []
    for version in versions:
        prompt = tidy(version.prompt)
        if prompt and prompt not in seen:
            seen.add(prompt)
            usable.append({"title": version.title.strip() or f"Version {len(usable) + 1}", "prompt": prompt})
    return usable


def _already_written(written):
    """
    For a later round: what the rounds before it wrote, by title, so its versions differ from them too, and one of
    them in full, so they read as one set. Without it, a later round came out in a style of its own.
    """
    titles = "; ".join(version["title"] for version in written)
    return (f"\n\n    This set already has {len(written)} versions, written before these: {titles}. Make each new one different "
            "from those as well as from each other. Write them in the same manner, at the same length and with the same "
            f"level of detail, as this earlier one:\n    {written[0]['prompt']}")


def write_prompts(image_jpegs, brief, count, llm_name, model=None, compose=False, transparent=False, refiner=None,
                  variety=variety_rules.DEFAULT, vary=(), keep=(), explicit=False, words=WORDS):
    """
    The set's title and {count} versions, from one request for up to round_size(words): the prompts have to know each other
    to differ, and it spends one of a free model's daily requests rather than {count}. More are written in even rounds
    (30 as 15 and 15), each told what the ones before it wrote and shown one of them; a reply cut off for want of
    tokens anyway is asked again half as many at a time.
    """
    rounds = math.ceil(count / round_size(_words(words, len(image_jpegs), compose, model)))
    written, title, size, seen = [], None, math.ceil(count / rounds), set()
    while len(written) < count:
        want = min(size, count - len(written))
        if written:
            # What this round is given from the ones before it (_already_written), so the log shows it.
            print(f"   The next {want} are told the {len(written)} written so far by title: "
                  f"{'; '.join(version['title'] for version in written)}")
            example = "\n".join("      " + line for line in written[0]["prompt"].splitlines())
            print(f"   and shown this one to write like:\n{example}")
        try:
            round_title, versions = _write_round(image_jpegs, brief, want, llm_name, model, compose, transparent, refiner,
                                                 variety, vary, keep, explicit, written, words)
        except CutOff:
            if want == 1:
                raise RuntimeError("The LLM's reply was cut off even for a single prompt.")
            size = (want + 1) // 2
            print(f"   ⚠️ The reply ran out of tokens: writing the prompts {size} at a time instead.")
            continue
        new = [version for version in versions if version["prompt"] not in seen]
        seen.update(version["prompt"] for version in new)
        written += new
        title = title or round_title
        # A round that came back short already asked again (and said so): going on with what there is.
        if len(new) < want:
            break
        if len(written) < count:
            print(f"   ✍️ {len(written)} of {count} prompts written.")
    if not written:
        raise RuntimeError("Could not get usable prompts.")
    return title, written[:count]


def _write_round(image_jpegs, brief, count, llm_name, model, compose, transparent, refiner, variety, vary, keep, explicit,
                 written, words=WORDS):
    """{count} versions from one request, asked again if the reply can't be used. Raises CutOff for a reply cut off."""
    instructions = _instructions(brief, count, len(image_jpegs), model, compose, transparent, variety, vary, keep, words)
    if explicit:
        instructions += explicit_rules.paragraph()
    if written:
        instructions += _already_written(written)
    tidy = _tidy(model, bool(image_jpegs))
    # A local model writes Fibo 2.0's captions as objects, in their own shape: as JSON inside a string it got them wrong.
    caption_objects = llm_name == "local" and model == models.FIBO2
    schema = fibo2_prompt.versions_schema(bool(image_jpegs)) if caption_objects else VERSIONS_SCHEMA
    best, title, problem = [], None, None
    for attempt in range(1, PROMPT_ATTEMPTS + 1):
        correction = f"\n\n    Your last reply came back with {problem}. Fix that." if problem else ""
        if llm_name == "local":
            reply = llm._ask(llm_name, instructions + correction, Versions, schema, image_jpegs, refiner=refiner)
        else:
            reply = llm._ask(llm_name, instructions + correction, Versions, schema, image_jpegs)
        try:
            versions = Versions.model_validate_json(fibo2_prompt.as_text(reply) if caption_objects else reply)
        except ValidationError as e:
            problem = f"an unreadable reply ({e.error_count()} errors)"
        except ValueError:  # Not JSON at all, caught turning its captions into text
            problem = "an unreadable reply (not JSON)"
        else:
            usable = _usable(versions.versions, tidy)
            # Extra ones were paid for and do no harm, so they're only left out.
            if len(usable) >= count:
                return versions.title.strip() or "Untitled", usable[:count]
            if len(usable) > len(best):
                best, title = usable, versions.title.strip() or "Untitled"
            problem = f"{len(usable)} different prompts instead of {count}"
        print(f"   ⚠️ The prompts came back with {problem} (attempt {attempt}/{PROMPT_ATTEMPTS}).")
    if best:
        print(f"   ⚠️ Going on with the {len(best)} it did write, rather than paying for more attempts.")
        return title, best
    raise RuntimeError(f"Could not get usable prompts: {problem}.")


def token_estimate(count, images=0, model=None, compose=False, transparent=False, variety=variety_rules.DEFAULT,
                   vary=(), keep=(), explicit=False, words=WORDS, brief=""):
    """
    What writing {count} prompts should take in tokens, before it starts: each prompt's, all written together, how
    many requests, and the largest request's context (the instructions, images, what the rounds before it wrote,
    and its reply), which is what has to fit the local model's 16k.
    """
    rounds = math.ceil(count / round_size(_words(words, images, compose, model)))
    size = math.ceil(count / rounds)
    each = prompt_tokens(_words(words, images, compose, model))
    instructions = _instructions(brief, size, images, model, compose, transparent, variety, vary, keep, words)
    if explicit:
        instructions += explicit_rules.paragraph()
    asked = len(instructions) // CHARS_PER_TOKEN + images * IMAGE_TOKENS
    # The last round is the largest: it is also told every title before it (about 6 tokens each) and shown one prompt.
    before = count - min(size, count) if rounds > 1 else 0
    handover = before * 6 + each if before else 0
    last = min(size, count - before) if rounds > 1 else count
    return {"each": each, "written": each * count, "rounds": rounds,
            "context": asked + handover + max(size, last) * each}
