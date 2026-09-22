"""
Google GenAI client for test suite generation, code generation, and repair.

Uses the native google-genai SDK (not the OpenAI compatibility shim).
All LLM interactions go through this module.
"""

import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from . import prompts

load_dotenv()


# ── Internals ────────────────────────────────────────────────────────────────


def _get_client() -> genai.Client:
    """Create a GenAI client using the configured API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file or as an environment variable."
        )
    return genai.Client(api_key=api_key)


def _get_model() -> str:
    """Return the model name from env or default."""
    return os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


def _extract_code(content: str) -> str:
    """Strip markdown code fences from LLM response, returning raw Python."""
    match = re.search(r"```(?:python)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else content).strip() + "\n"


def _extract_markdown(content: str) -> str:
    """Strip markdown fences if the LLM wraps the output."""
    match = re.search(r"```(?:markdown)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else content).strip() + "\n"


def _request(system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    """
    Send a generation request to GenAI with automatic retry on transient errors.

    Retries up to 3 times on server errors (500/502/503/504).
    Hard-fails immediately on quota exhaustion (429).
    """
    model = model or _get_model()
    client = _get_client()

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.2,
    )

    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )
            content = response.text or ""
            if not content.strip():
                raise RuntimeError("GenAI returned an empty response")
            return content

        except Exception as error:
            last_error = error
            error_str = str(error).lower()

            # Quota exhaustion — no point retrying
            if "429" in error_str or "quota" in error_str or "rate limit" in error_str:
                raise RuntimeError(
                    "GenAI quota exhausted. Wait for the quota to reset or "
                    "use an API key with available billing/quota."
                ) from error

            # Last attempt — give up
            if attempt == 2:
                raise RuntimeError(
                    f"GenAI request failed after 3 attempts: {error}"
                ) from error

            # Transient error — retry with backoff
            wait = 2 ** attempt
            print(f"  [GenAI] Transient error (attempt {attempt + 1}/3), "
                  f"retrying in {wait}s: {error}")
            time.sleep(wait)

    # Should never reach here, but just in case
    raise RuntimeError(f"GenAI request failed: {last_error}")


# ── Public API ───────────────────────────────────────────────────────────────


def generate_test_suite(
    url: str,
    snapshot: str,
    instructions: str,
    test_type: str = "ui",
) -> str:
    """
    Generate a structured test suite .md from the application URL,
    browser snapshot, and user instructions.

    This is the key differentiator: the AI creates the test specification
    dynamically based on what it actually sees on the page.
    """
    user_prompt = (
        f"APPLICATION URL: {url}\n\n"
        f"TEST TYPE: {test_type.upper()}\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
    )
    if snapshot:
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n"

    print("  [GenAI] Generating test suite specification...")
    content = _request(prompts.SUITE_GENERATION_SYSTEM, user_prompt)
    return _extract_markdown(content)


def generate_test_code(
    suite_md: str,
    snapshot: str,
    test_type: str = "ui",
) -> str:
    """
    Generate executable pytest code from a test suite .md and browser snapshot.
    """
    system = (
        prompts.UI_CODE_GENERATION_SYSTEM
        if test_type == "ui"
        else prompts.API_CODE_GENERATION_SYSTEM
    )

    user_prompt = f"TEST SUITE SPECIFICATION:\n{suite_md}\n\n"
    if snapshot:
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n"

    print("  [GenAI] Generating executable test code...")
    content = _request(system, user_prompt)
    return _extract_code(content)


def repair_test_code(
    suite_md: str,
    snapshot: str,
    current_code: str,
    failure_output: str,
    test_type: str = "ui",
) -> str:
    """
    Repair failing test code by sending the suite, snapshot, current code,
    and failure traceback to the AI for correction.
    """
    system = (
        prompts.UI_REPAIR_SYSTEM
        if test_type == "ui"
        else prompts.API_REPAIR_SYSTEM
    )

    parts = [f"TEST SUITE SPECIFICATION:\n{suite_md}\n"]
    if snapshot:
        parts.append(f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n")
    parts.append(f"CURRENT TEST CODE:\n{current_code}\n")
    parts.append(f"PYTEST FAILURE OUTPUT:\n{failure_output}\n")

    user_prompt = "\n".join(parts)

    print("  [GenAI] Analyzing failure and generating repair...")
    content = _request(system, user_prompt)
    return _extract_code(content)
