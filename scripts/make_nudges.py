"""Asks Gemini, once, for the idle nudges Status shows when nothing is running ("Why don't you make something ...?"),
and saves them to panel/nudges.json, which the panel reads. Run it again for a fresh set:

    python scripts/make_nudges.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from core.gemini import _generate  # noqa: E402

OUT = os.path.join(ROOT, "panel", "nudges.json")
COUNT = 100
PROMPT = f"""Write {COUNT} short, different one-line nudges for an app that makes AI images and videos. Each one gently
invites the user to make something, in the spirit of "Why don't you make something ___?" but vary the wording and the
idea a lot: moods, colours, places, eras, textures, weather, small and big subjects, playful and calm. Keep each under
70 characters, friendly and understated, never pushy, no emoji, no quotation marks, no numbering, nothing adult.
Answer with a JSON array of {COUNT} strings and nothing else."""


QUESTION = re.compile(r"^(why|what|how|ever|could|can|would|have|is|are|do|did|will|shall|who|where|when)\b", re.I)


def punctuate(line):
    """Gemini often leaves the end bare: a question gets its mark, the rest a full stop."""
    return line if line[-1] in ".!?" else line + ("?" if QUESTION.match(line) else ".")


def main():
    response = _generate(PROMPT)
    text = (response.text or "").strip()
    match = re.search(r"\[[\s\S]*\]", text)
    lines = json.loads(match.group(0) if match else text)
    seen, nudges = set(), []
    for line in lines:
        line = " ".join(str(line).split()).strip(" \"'")
        if line and len(line) <= 90 and line.lower() not in seen:
            seen.add(line.lower())
            nudges.append(punctuate(line))
    if len(nudges) < COUNT * 0.8:
        raise SystemExit(f"Gemini gave only {len(nudges)} usable lines; nothing saved.")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(nudges, f, ensure_ascii=False, indent=1)
    print(f"Saved {len(nudges)} nudges to {OUT}")


if __name__ == "__main__":
    main()
