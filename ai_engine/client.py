"""
Ollama client for test suite generation, code generation, and repair.

Uses the Ollama local REST API endpoint (http://localhost:11434/api/chat).
All LLM interactions go through this module.
"""

import os
import re
import time
import json
import requests

from dotenv import load_dotenv
from . import prompts

load_dotenv()

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")


# -- Internals ----------------------------------------------------------------

def _get_model() -> str:
    """Return the model name from env or default."""
    # Based on the user's available tags, gemma4:latest is the smartest option
    return os.getenv("OLLAMA_MODEL", "gemma4:latest")


def _extract_code(content: str) -> str:
    """Strip markdown code fences from LLM response, returning raw Python."""
    match = re.search(r"```(?:python|py)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else content).strip() + "\n"


def _extract_markdown(content: str) -> str:
    """Strip markdown fences if the LLM wraps the output."""
    match = re.search(r"```(?:markdown|md)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else content).strip() + "\n"


def _request(system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    """
    Send a generation request to the local Ollama instance.
    """
    model = model or _get_model()
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }

    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(OLLAMA_URL, json=payload, timeout=300)
            response.raise_for_status()
            
            data = response.json()
            content = data.get("message", {}).get("content", "")
            
            if not content.strip():
                raise RuntimeError("Ollama returned an empty response")
            return content

        except requests.exceptions.RequestException as error:
            last_error = error
            print(f"  [Ollama] Connection error (attempt {attempt + 1}/3): {error}")
            time.sleep(2)
        except Exception as error:
            last_error = error
            print(f"  [Ollama] Transient error (attempt {attempt + 1}/3): {error}")
            time.sleep(2)

    raise RuntimeError(f"Ollama request failed after 3 attempts: {last_error}")


# -- Public API ----------------------------------------------------------------

def generate_test_suite(
    url: str,
    snapshot: str,
    instructions: str,
    test_type: str = "ui",
) -> str:
    """
    Generate a structured test suite .md from the application URL,
    browser snapshot, and user instructions.
    """
    user_prompt = (
        f"APPLICATION URL: {url}\n\n"
        f"TEST TYPE: {test_type.upper()}\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
    )
    if snapshot:
        user_prompt += f"BROWSER ACCESSIBILITY SNAPSHOT:\n{snapshot}\n"

    print(f"  [Ollama] Generating test suite specification using {_get_model()}...")
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

    print(f"  [Ollama] Generating executable test code using {_get_model()}...")
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
    
    # Give the local model explicit guidance on the repair format
    parts.append("\nIMPORTANT INSTRUCTION: Return ONLY the raw Python code. Wrap it in ```python fences.")

    user_prompt = "\n".join(parts)

    print(f"  [Ollama] Analyzing failure and generating repair using {_get_model()}...")
    content = _request(system, user_prompt)
    return _extract_code(content)
