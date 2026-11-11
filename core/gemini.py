"""Calling Gemini: moves straight on to the next model on any error. Both pipelines go through this."""
import os
import re
import threading
import time

from google import genai

from core.api_log import is_daily_quota, is_exhausted, log_api_call, log_api_error, mark_exhausted
from core.gemini_models import get_text_models

# Gemini returns these when it is overloaded or rate-limiting rather than when
# the request itself is wrong, so they are worth waiting out.
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)

# Longest a single retry will sleep. A daily-quota 429 reports delays far past
# anything worth blocking a run on.
MAX_RETRY_WAIT = 90


def _get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Create a .env file or set the environment variable before running.")
    return genai.Client(api_key=api_key)

def _is_retryable(error):
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if status in RETRYABLE_STATUSES:
        return True
    # Not every client error exposes a numeric code, so fall back to the text.
    text = str(error)
    return any(str(code) in text for code in RETRYABLE_STATUSES)

def _retry_delay(error):
    """
    Reads the retryDelay Gemini attaches to a 429. Plain backoff is often
    shorter than what the server actually wants, which just burns the retries.
    """
    match = re.search(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", str(error))
    if not match:
        return None
    # Cap it: a daily quota reports delays no run should sit and wait out.
    return min(float(match.group(1)) + 1, MAX_RETRY_WAIT)

# A text reply normally takes a few seconds. A model that says nothing for this
# long is overloaded or stuck (it happens, with no error at all), so move on.
DEFAULT_TIMEOUT = 90

# Models that no longer exist, in this process: later calls skip them.
_skipped_models = set()

# Models that failed for a moment (overloaded, rate-limited, silent), until when: later calls try the
# others first.
COOLDOWN = 60
_cooldowns = {}


def _call_with_deadline(fn, seconds):
    """
    Runs fn, raising TimeoutError if it has not returned within `seconds`. The
    SDK can sit on a silent request (or a long retry-after) indefinitely, so the
    call runs in a daemon thread that is simply abandoned if it hangs.
    """
    result = {}

    def target():
        try:
            result["value"] = fn()
        except BaseException as e:
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise TimeoutError(f"no response within {seconds}s")
    if "error" in result:
        raise result["error"]
    return result["value"]


def _cooling(model):
    return _cooldowns.get(model, 0) > time.time()


def _generate(prompt, retries=4, models=None, config=None, timeout=None):
    """
    Calls Gemini. Any error (timeout, overload, a per-minute limit, a used-up daily
    quota, a retired model) hands over to the next model at once, never waiting on
    the one that failed. A model that failed for a moment sits out COOLDOWN seconds
    so later calls don't run into it again. Only when every model has failed does
    it wait and go through the chain again, up to `retries` passes in all; it
    raises after that, or at once if nothing it saw was worth another pass.
    """
    client = _get_client()
    timeout = timeout or int(os.getenv("GEMINI_TIMEOUT") or DEFAULT_TIMEOUT)
    chain = list(models or get_text_models())
    errors = []

    for sweep in range(max(retries, 1)):
        usable = []
        for model in chain:
            if model in _skipped_models:
                continue
            if is_exhausted(model):
                note = f"{model} (daily quota used up)"
                if note not in errors:
                    errors.append(note)
                continue
            usable.append(model)
        # With all of them cooling down, trying is better than failing outright.
        order = [m for m in usable if not _cooling(m)] or usable
        if not order:
            break
        again, delays = False, []
        for model in order:
            try:
                response = _call_with_deadline(
                    lambda: client.models.generate_content(model=model, contents=prompt, config=config), timeout)
                log_api_call("Gemini", model)
                return response
            except Exception as e:
                log_api_error("Gemini", model, e)
                if isinstance(e, TimeoutError):
                    print(f"   ⚠️ {model} did not answer within {timeout}s. Trying the next model...")
                    _cooldowns[model] = time.time() + COOLDOWN
                    again = True
                elif is_daily_quota(e):
                    print(f"   ⚠️ {model} has used its daily quota. Trying the next model...")
                    mark_exhausted(model, e)
                elif getattr(e, "code", None) == 404:
                    print(f"   ⚠️ {model} no longer exists. Trying the next model...")
                    _skipped_models.add(model)
                elif _is_retryable(e):
                    print(f"   ⚠️ {model} unavailable. Trying the next model...")
                    _cooldowns[model] = time.time() + COOLDOWN
                    again = True
                    delays.append(_retry_delay(e))
                else:
                    print(f"   ⚠️ {model} failed ({type(e).__name__}). Trying the next model...")
                if model not in errors:
                    errors.append(model)
        if not again or sweep == retries - 1:
            break
        known = [d for d in delays if d]
        wait = min(known) if known else 2 ** (sweep + 1)
        print(f"   ⚠️ Every model is unavailable (pass {sweep+1}/{retries}). Retrying in {wait:.0f}s...")
        time.sleep(wait)

    raise RuntimeError(f"Gemini failed on every model ({', '.join(errors)}). See logs/api_errors.log.")
