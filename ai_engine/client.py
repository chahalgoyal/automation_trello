"""
Groq client for test suite generation, code generation, and repair.

Uses the native groq SDK with rate-limit-aware pacing for the free tier.
All LLM interactions go through this module.
"""

import os
import re
import time

from dotenv import load_dotenv
from groq import Groq

from . import prompts

load_dotenv()

# -- Free-tier budget management -----------------------------------------------
# Groq free tier for gpt-oss-120b: 8000 TPM (tokens per minute).
# We pace calls so the per-minute budget has time to refresh.

_last_call_time: float = 0.0       # epoch seconds of last successful call
_PACE_SECONDS: float = 20.0        # minimum gap between calls (3 calls / min)
_RATE_LIMIT_WAIT: float = 65.0     # wait on 429 for TPM to fully reset


# -- Internals ----------------------------------------------------------------


def _get_client() -> Groq:
    """Create a Groq client using the configured API key."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. "
            "Set it in your .env file or as an environment variable."
        )
    return Groq(api_key=api_key.strip())


def _get_model() -> str:
    """Return the model name from env or default."""
    return os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _extract_code(content: str) -> str:
    """Strip markdown code fences from LLM response, returning raw Python."""
    match = re.search(r"```(?:python)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else content).strip() + "\n"


def _extract_markdown(content: str) -> str:
    """Strip markdown fences if the LLM wraps the output."""
    match = re.search(r"```(?:markdown)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else content).strip() + "\n"


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending a note if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n... [TRUNCATED] ..."


def _pace():
    """Wait if needed to avoid hitting the per-minute token budget."""
    global _last_call_time
    if _last_call_time > 0:
        elapsed = time.time() - _last_call_time
        if elapsed < _PACE_SECONDS:
            wait = _PACE_SECONDS - elapsed
            print(f"  [Groq] Pacing: waiting {wait:.0f}s for rate limit budget...")
            time.sleep(wait)


def _request(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    max_tokens: int = 2000,
) -> str:
    """
    Send a generation request to Groq with rate-limit-aware retry.
    """
    global _last_call_time
    model = model or _get_model()
    client = _get_client()

    # Pace between calls
    _pace()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    last_error = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
            )
            _last_call_time = time.time()

            content = response.choices[0].message.content or ""
            if not content.strip():
                raise RuntimeError("Groq returned an empty response")
            return content

        except Exception as error:
            last_error = error
            error_str = str(error).lower()

            # Auth errors — don't retry
            if "401" in error_str or ("403" in error_str and "network" in error_str):
                raise RuntimeError(
                    f"Groq API Error (auth): {error}"
                ) from error

            # Rate limit — wait for the full minute to reset
            if "429" in error_str or "413" in error_str or "rate_limit" in error_str:
                if attempt < 2:
                    print(f"  [Groq] Rate limited (attempt {attempt + 1}/3), "
                          f"waiting {_RATE_LIMIT_WAIT:.0f}s for budget to reset...")
                    time.sleep(_RATE_LIMIT_WAIT)
                    _last_call_time = time.time()
                    continue

            # Last attempt — give up
            if attempt == 2:
                raise RuntimeError(
                    f"Groq request failed after 3 attempts: {error}"
                ) from error

            # Other transient error — short backoff
            wait = 2 ** attempt
            print(f"  [Groq] Transient error (attempt {attempt + 1}/3), "
                  f"retrying in {wait}s: {error}")
            time.sleep(wait)

    raise RuntimeError(f"Groq request failed: {last_error}")


# -- Public API ----------------------------------------------------------------


def generate_test_suite(
    url: str,
    snapshot: str,
    instructions: str,
    test_type: str = "ui",
) -> str:
    # Keep prompt compact: snapshot is the largest part
    user_prompt = (
        f"APPLICATION URL: {url}\n\n"
        f"TEST TYPE: {test_type.upper()}\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
    )
    if snapshot:
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{_truncate(snapshot, 6000)}\n"

    print("  [Groq] Generating test suite specification...")
    content = _request(prompts.SUITE_GENERATION_SYSTEM, user_prompt, max_tokens=2000)
    return _extract_markdown(content)


def generate_test_code(
    suite_md: str,
    snapshot: str,
    test_type: str = "ui",
) -> str:
    system = (
        prompts.UI_CODE_GENERATION_SYSTEM
        if test_type == "ui"
        else prompts.API_CODE_GENERATION_SYSTEM
    )

    user_prompt = f"TEST SUITE SPECIFICATION:\n{_truncate(suite_md, 5000)}\n\n"
    if snapshot:
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{_truncate(snapshot, 4000)}\n"

    print("  [Groq] Generating executable test code...")
    content = _request(system, user_prompt, max_tokens=3000)
    return _extract_code(content)


def repair_test_code(
    suite_md: str,
    snapshot: str,
    current_code: str,
    failure_output: str,
    test_type: str = "ui",
) -> str:
    system = (
        prompts.UI_REPAIR_SYSTEM
        if test_type == "ui"
        else prompts.API_REPAIR_SYSTEM
    )

    # For repair, prioritize code + error. Skip snapshot entirely,
    # keep suite summary minimal. This keeps us well under 8000 TPM.
    parts = [
        f"CURRENT TEST CODE:\n{_truncate(current_code, 6000)}\n",
        f"PYTEST FAILURE OUTPUT:\n{_truncate(failure_output, 3000)}\n",
        f"TEST SUITE (summary):\n{_truncate(suite_md, 2000)}\n",
    ]
    user_prompt = "\n".join(parts)

    print("  [Groq] Analyzing failure and generating repair...")
    content = _request(system, user_prompt, max_tokens=3000)
    return _extract_code(content)
