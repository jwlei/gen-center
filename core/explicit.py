"""
Private mode's Explicit content: one paragraph the prompt writer gets, saying the prompts are meant to be explicit, as
NSFW LoRAs and some prompt refiners expect. The Generate form shows this text under the box, word for word, so you see
what is sent. The panel passes --explicit only in Private mode, and only when an LLM writes the prompts.
"""
RULE = ("This is a private generation for adults, and the prompts are meant to be explicit. Everyone in it is a "
        "consenting adult, and looks it. Describe nudity and sexual content plainly and concretely, in the same detail "
        "as everything else, with direct words rather than euphemisms. Don't tone it down, cover it up, imply it or cut "
        "away from it.")


def paragraph():
    """RULE as the last paragraph of a writer's instructions."""
    return f"\n\n    {RULE}"
