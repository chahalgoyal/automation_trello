"""
Google GenAI client for test suite generation, code generation, and repair.

Uses the native google-genai SDK.
Supports robust retry logic for transient 503 errors via exponential backoff.
All LLM interactions go through this module.
"""

import os
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


def _strip_fences(content: str, lang_tags: tuple) -> str:
    """
    Extract the body of the first markdown code fence without regex.

    Splits on ``` to avoid reluctant-quantifier backtracking (S6019).
    lang_tags: lowercase language identifiers to strip from the opening line
               (e.g. ("python", "py", "") or ("markdown", "md", "")).
    """
    parts = content.split("```")
    if len(parts) < 3:
        return content.strip() + "\n"
    inner = parts[1]
    newline_pos = inner.find("\n")
    if newline_pos != -1 and inner[:newline_pos].strip().lower() in lang_tags:
        inner = inner[newline_pos + 1 :]
    return inner.strip() + "\n"


def _extract_code(content: str) -> str:
    """Strip markdown code fences from LLM response, returning raw Python."""
    return _strip_fences(content, ("python", "py", ""))


def _extract_markdown(content: str) -> str:
    """Strip markdown fences if the LLM wraps the output."""
    return _strip_fences(content, ("markdown", "md", ""))


# Fallback pool for this specific API key's available models
FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
]


def _classify_model_error(error_str: str) -> str:
    """
    Classify a GenAI error string into an action.

    Returns:
        "switch"  — skip to the next model immediately
        "retry"   — apply backoff and retry the same model
    """
    is_quota = "429" in error_str and (
        "quota" in error_str or "rate limit" in error_str
    )
    is_unavailable = "404" in error_str or "not available" in error_str
    if is_quota or is_unavailable:
        return "switch"
    return "retry"


def _handle_retry_error(error: Exception, attempt: int, model_name: str) -> None:
    """
    Handle an error from a single model attempt.

    Raises RuntimeError("skip:...") if the model should be abandoned.
    Otherwise applies exponential backoff and returns to allow a retry.
    Extracted from _try_model to reduce its cognitive complexity (S3776).
    """
    error_str = str(error).lower()
    action = _classify_model_error(error_str)

    if action == "switch":
        label = "quota exhausted (429)" if "429" in error_str else "unavailable (404)"
        print(f"  [GenAI] {model_name} {label}. Switching to next model...")
        raise RuntimeError(f"skip:{error}") from error

    if attempt == 4:
        print(
            f"  [GenAI] {model_name} failed after 5 attempts."
            " Falling back to next model..."
        )
        raise RuntimeError(f"skip:{error}") from error

    wait = 4**attempt  # 1s, 4s, 16s, 64s
    print(
        f"  [GenAI] {model_name} transient error (attempt {attempt + 1}/5), "
        f"retrying in {wait}s: {error}"
    )
    time.sleep(wait)


def _try_model(client, model_name: str, user_prompt: str, config) -> str:
    """
    Attempt up to 5 times to get a non-empty response from a single model.

    Returns the response text on success.
    Raises RuntimeError("skip:...") if the model should be abandoned.
    """
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=config,
            )
            content = response.text or ""
            if not content.strip():
                raise RuntimeError("GenAI returned an empty response")
            return content
        except Exception as error:
            _handle_retry_error(error, attempt, model_name)

    raise RuntimeError("Unreachable")  # pragma: no cover


def _request(system_prompt: str, user_prompt: str) -> str:
    """
    Send a generation request to GenAI with automatic retry on transient errors.

    If a model fails 5 times (e.g. 503 High Demand), it globally falls back
    to the next model in the FALLBACK_MODELS list.
    Hard-fails immediately on quota exhaustion (429).
    """
    client = _get_client()

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.2,
    )

    last_error = None

    for model_name in FALLBACK_MODELS:
        print(f"  [GenAI] Attempting request with model: {model_name}...")
        try:
            return _try_model(client, model_name, user_prompt, config)
        except RuntimeError as error:
            last_error = error

    raise RuntimeError(
        f"GenAI request failed on all fallback models. Last error: {last_error}"
    )


# ── Public API ────────────────────────────────────────────────────────────────


def generate_ui_test_suite(
    url: str,
    snapshot: str,
    instructions: str,
) -> str:
    """
    Generate a structured UI test suite .md from the application URL,
    browser snapshot, and user instructions.
    """
    user_prompt = (
        f"APPLICATION URL: {url}\n\n"
        f"TEST TYPE: UI\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
    )
    if snapshot:
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n"

    print("  [GenAI] Generating UI test suite specification...")
    content = _request(prompts.UI_SUITE_GENERATION_SYSTEM, user_prompt)
    return _extract_markdown(content)


def generate_api_test_suite(
    url: str,
    readme_content: str,
    instructions: str,
) -> str:
    """
    Generate a structured API test suite .md from the base API URL,
    project README/API documentation, and user instructions.
    """
    user_prompt = (
        f"BASE API URL: {url}\n\n"
        f"TEST TYPE: API\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
        f"API DOCUMENTATION (README):\n{readme_content}\n"
    )

    print("  [GenAI] Generating API test suite specification...")
    content = _request(prompts.API_SUITE_GENERATION_SYSTEM, user_prompt)
    return _extract_markdown(content)


def generate_test_code(
    suite_md: str,
    snapshot: str,
    test_type: str = "ui",
) -> str:
    """
    Generate executable pytest code from a test suite .md
    and (optionally) a browser snapshot.
    """
    system = (
        prompts.UI_CODE_GENERATION_SYSTEM
        if test_type == "ui"
        else prompts.API_CODE_GENERATION_SYSTEM
    )

    user_prompt = f"TEST SUITE SPECIFICATION:\n{suite_md}\n\n"
    if snapshot and test_type == "ui":
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n"

    print(f"  [GenAI] Generating executable {test_type.upper()} test code...")
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
        prompts.UI_REPAIR_SYSTEM if test_type == "ui" else prompts.API_REPAIR_SYSTEM
    )

    parts = [f"TEST SUITE SPECIFICATION:\n{suite_md}\n"]
    if snapshot and test_type == "ui":
        parts.append(f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n")
    parts.append(f"CURRENT TEST CODE:\n{current_code}\n")
    parts.append(f"PYTEST FAILURE OUTPUT:\n{failure_output}\n")

    user_prompt = "\n".join(parts)

    print(f"  [GenAI] Analyzing {test_type.upper()} failure and generating repair...")
    content = _request(system, user_prompt)
    return _extract_code(content)
