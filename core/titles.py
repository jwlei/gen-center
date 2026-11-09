"""
Gemini titles (Settings): a short descriptive title for a new film or image set, written by Gemini from its prompt,
in place of the one it would get otherwise (the LLM's, or an exact prompt's first words). It names the files too.
When Gemini refuses the prompt (it blocks NSFW ones) or fails, the local model (Settings) titles it instead, unless
the local model already wrote its prompts, and with them its title. Off, without a Gemini key, or when both fail, the
run keeps its own title and goes on.
"""
import json
import os

from core.gemini import _generate
from panel import settings as panel_settings

PROMPT = ("Write a short descriptive title, 2 to 5 words in Title Case, for {what} made from the prompt below. "
          "Say what it shows, so it stands apart from others. Reply with the title only: no quotes, no punctuation "
          "at the end.\n\nPrompt:\n{prompt}")
MOST_WORDS = 8
MOST_CHARACTERS = 80
# A title is a few words: past this the prompt adds nothing, and a long one costs more.
MOST_PROMPT = 4000
TIMEOUT = 30
TITLE_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"],
                "additionalProperties": False}


def wanted():
    """Whether Settings asks for Gemini titles, and Gemini can be asked."""
    try:
        return bool(panel_settings.load().get("gemini_titles")) and bool(os.getenv("GEMINI_API_KEY"))
    except (OSError, ValueError):
        return False


def clean(text):
    """The title out of Gemini's reply: one line, a few words, no quotes or closing punctuation."""
    line = next((line for line in (text or "").splitlines() if line.strip()), "")
    words = line.strip().strip("\"'“”‘’*#").split()[:MOST_WORDS]
    return " ".join(words).rstrip(".!:;,")[:MOST_CHARACTERS].strip()


def gemini_title(prompt, what):
    """Gemini's title for it, or None if it could not give one."""
    try:
        reply = _generate(PROMPT.format(what=what, prompt=prompt[:MOST_PROMPT]), retries=2, timeout=TIMEOUT)
    except Exception as e:  # A title is never worth stopping a run for
        print(f"   ⚠️ Gemini could not title it ({e}); it keeps its own title.")
        return None
    title = clean(getattr(reply, "text", "")) or None
    if not title:
        feedback = getattr(reply, "prompt_feedback", None)
        reason = getattr(getattr(feedback, "block_reason", None), "name", None)
        print(f"   ⚠️ Gemini gave no title{f' (it refused the prompt: {reason})' if reason else ''}.")
    return title


def local_title(prompt, what, comfy_url):
    """The local model's title for it, or None. Starting it frees ComfyUI's models first, as writing prompts does."""
    from core import h3_refiner  # Only when needed: it brings the local model's tooling with it
    try:
        with h3_refiner.Refiner(comfy_url, require_compiler=False, model_id=h3_refiner.local_llm_model()) as refiner:
            reply = refiner.plan(PROMPT.format(what=what, prompt=prompt[:MOST_PROMPT]), TITLE_SCHEMA)
        return clean(json.loads(reply).get("title")) or None
    except Exception as e:  # A title is never worth stopping a run for
        print(f"   ⚠️ The local model could not title it either ({e}); it keeps its own title.")
        return None


def titled(title, prompt, what, comfy_url=None, llm=None):
    """
    title, or Gemini's in its place when Settings asks for it; the local model's when Gemini gives none, unless the
    local model (llm "local") wrote the prompts and so its title already.
    """
    if not (prompt or "").strip() or not wanted():
        return title
    better = gemini_title(prompt, what)
    if better:
        print(f"🏷️ Gemini titled it: {better}")
        return better
    if comfy_url and llm != "local":
        print("🏷️ Asking the local model for a title instead...")
        better = local_title(prompt, what, comfy_url)
        if better:
            print(f"🏷️ The local model titled it: {better}")
    return better or title
