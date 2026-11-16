"""
Why a run failed, read from its log: in plain words with what to do (explain_failure), and whether ComfyUI is
restarted and the run tried once more (restart_reason). Pure functions over a job's lines ({"n", "text", "k"}), so
they can be tested without the panel; server.py acts on what they say.
"""
import re

# A Generate the panel turned down: logged with this mark, and never taken for why a run failed.
REFUSED = "🚫"

# The lines that say what went wrong, as the pipelines print them.
TROUBLE = re.compile(r"❌|⚠️|Error|Exception|Traceback|failed|refused|can't|could not", re.I)
MOST_WHY_LINES = 4
# ComfyUI's memory compiler (comfy-aimdo) failing: a fresh ComfyUI clears it, so it is restarted and tried once more.
AIMDO_ERROR = re.compile(r"aimdo memory compile error", re.I)
SETTINGS_REFUSED = re.compile(r"Can't use the LoRA|\bis one of\b|Value not in list|isn't installed|"
                              r"prompt_outputs_failed_validation|Prompt outputs failed validation|ComfyUI rejected the workflow|"
                              r"options need it listed again|the workflow can't run", re.I)
# The run got as far as rendering: an image, clip, shot or scene under way, ComfyUI failing or out of reach, or a GPU
# error. Not the panel's own lines about ComfyUI after a run (its cleanup), which every run gets.
REACHED_COMFYUI = re.compile(r"(?:Image|Clip|Shot|Scene) \d+(?:/| of )\d+|ComfyUI · |\bComfyUI (?:failed|rejected|"
                             r"stopped|crashed|is too busy|didn't|did not|isn't|is not)|reach ComfyUI|\bCUDA\b|"
                             r"out of memory|\btorch\b", re.I)
EXIT_ONE_ERROR = re.compile(r"\b(?:exit(?:ed)? (?:with )?(?:(?:exit )?code |status )?1|returned non-zero exit status 1)\b", re.I)


def hit_aimdo(job):
    """Whether the job that just ended stopped on ComfyUI's aimdo memory compile error."""
    return any(AIMDO_ERROR.search(line["text"]) for line in job.lines if line["n"] > getattr(job, "first_line", 0))


def live_crash_reason(job):
    if hit_aimdo(job):
        return "ComfyUI's aimdo memory compile error"
    if any(EXIT_ONE_ERROR.search(line["text"]) for line in job.lines if line["n"] > getattr(job, "first_line", 0)):
        return "exit code 1"
    return None


def restart_reason(job, code):
    """
    Why ComfyUI is restarted, and the run tried once more, after this failure, said as it reads in the log; None for a
    failure it isn't restarted for. ComfyUI's aimdo error needs a fresh ComfyUI. Exit 1 is the run's own failure code,
    and one of the ways a ComfyUI that has died or hung shows.
    """
    if hit_aimdo(job):
        return "ComfyUI's aimdo memory compile error"
    # Refused for what it asked for (a file ComfyUI doesn't have, an option out of its list): a fresh ComfyUI refuses it too.
    if any(SETTINGS_REFUSED.search(line["text"]) for line in job.lines if line["n"] > getattr(job, "first_line", 0)):
        return None
    reason = live_crash_reason(job)
    if reason:
        return reason
    # Exit 1 before anything reached ComfyUI (a missing API key, an LLM's refusal or quota, a bad plan): a fresh ComfyUI
    # changes nothing, so it goes to Failed at once instead of restarting ComfyUI and trying again.
    if code == 1 and any(line.get("k") == "comfy" or (line.get("k") != "dim" and REACHED_COMFYUI.search(line["text"]))
                         for line in job.lines if line["n"] > getattr(job, "first_line", 0)):
        return "exit code 1"
    return None


# The failures that come up, in plain words with what to do: the first whose pattern is in the run's log.
FAILURES = (
    (r"Masked AV requires a current ComfyUI build",
     "H3 Infinite continuation could not confirm ComfyUI's MiniMax H3 masks. Update ComfyUI and restart it; another "
     "H3 node pack wrapping MiniMax H3 can also hide them from the suite's check. Then continue: clip 1 is kept."),
    (r"out of memory|OutOfMemoryError|CUDA error: out of memory|not enough (GPU )?memory|allocation on device",
     "Out of GPU memory. Try a smaller size (1 MP), fewer references, or turn off SeedVR2 or the 2nd pass under Workflow options."),
    (r"Needs the node [^,]+, which isn't installed|missing_node_type|node type .* not found|does not exist in the node",
     "A node this workflow needs isn't installed in ComfyUI. Install it with ComfyUI Manager, or turn off the option that uses it."),
    (r"Can't use the LoRA",
     "A LoRA this run saved isn't one ComfyUI has any more (renamed or moved): its images failed, the rest were made. "
     "To test it, start a new comparison and pick it from the list."),
    (r"is not installed|Value not in list: (ckpt|unet|vae|lora|clip|model)_name|No such file or directory: .*models",
     "A model file this workflow needs isn't in ComfyUI's models folder. Download it there, then continue."),
    (r"ComfyUI isn't running|Connection refused|Max retries exceeded|Failed to establish a new connection|ConnectionError",
     "ComfyUI wasn't running, or stopped answering. Start it (Generate starts it when COMFYUI_LAUNCHER is set), then continue."),
    (r"ComfyUI rejected the workflow|prompt_outputs_failed_validation|Prompt outputs failed validation",
     "ComfyUI refused the workflow as sent: something it expects is missing or out of range. The lines below say what."),
    (r"\b429\b|RESOURCE_EXHAUSTED|exceeded your current quota|rate limit",
     "The LLM's quota is used up for now (Gemini's free tier allows 20 a day per model). Choose another available provider, or try again later."),
    (r"\b503\b|UNAVAILABLE|overloaded|high demand",
     "The LLM was too busy to answer. Continue to try again: what was done is kept."),
    (r"has no credentials|invalid api.?key|Unauthorized|\b401\b",
     "The LLM has no working API key. Set it in .env (see .env.example)."),
    (r"rejected on all \d+ tries|failed on all \d+ tries",
     "Every try was rejected by the check (a broken frame, or lip-sync that didn't match). Try another seed, or a shorter line."),
    (r"No space left on device|disk is full",
     "The disk is full. Delete old output, or clear finished runs, then continue."),
    (r"timed out|Timeout|took longer than",
     "It took longer than allowed (COMFYUI_TIMEOUT in .env). A bigger size or more steps take longer: continue, or raise the limit."),
)


def explain_failure(job, code):
    """
    (In plain words, or None) and the run's own lines that say what went wrong. The plain words are for the failures
    that come up again and again; anything else shows only its lines.
    """
    said = why_it_failed(job, code)
    # The run's last lines that say what went wrong: a warning it got past earlier isn't why it stopped.
    plain = next((say for pattern, say in FAILURES if re.search(pattern, said, re.I)), None)
    return plain, said


def why_it_failed(job, code):
    """The run's own last lines that say what went wrong, or that it didn't say."""
    lines = [line["text"].strip() for line in job.lines if line["n"] > getattr(job, "first_line", 0)]
    # A Generate turned down meanwhile is about another job, not this one.
    said = [line for line in lines if TROUBLE.search(line) and not line.startswith(("=====", REFUSED))]
    if said:
        return "\n".join(dict.fromkeys(said[-MOST_WHY_LINES:]))
    last = lines[-1] if lines else "nothing"
    return f"It ended (exit {code}) without saying why. Its last line: {last}"
