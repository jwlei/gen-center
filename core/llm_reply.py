"""What an LLM's reply can say about itself, for whoever asked it."""


class CutOff(RuntimeError):
    """The reply ran out of tokens before it was done: asking for less at a time is what helps."""
