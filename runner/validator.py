"""
Validation utilities for generated test code.

Provides:
- Python syntax validation before running pytest
- Failure classification for intelligent reporting
- JSON report writing for the attempt history
"""

import json
from pathlib import Path


def validate_python(test_file: Path) -> None:
    """
    Validate that a file is syntactically correct Python with test functions.

    Raises:
        SyntaxError: If the file contains invalid Python syntax
        ValueError: If the file has no pytest test functions
    """
    source = test_file.read_text(encoding="utf-8")
    compile(source, str(test_file), "exec")

    if "def test_" not in source:
        raise ValueError(
            f"Generated file {test_file.name} does not contain any "
            f"pytest test functions (def test_...)"
        )


def classify_failure(output: str) -> str:
    """
    Categorize a test failure for structured reporting.

    Returns one of:
        - "blocked_network"      : network/connectivity issue
        - "blocked_ai_quota"     : AI API quota exhausted
        - "blocked_credentials"  : authentication/credential issue
        - "timeout"              : execution timed out
        - "no_tests_collected"   : pytest found no test functions
        - "syntax_error"         : Python syntax error
        - "import_error"         : missing module/dependency
        - "failed_test"          : actual test assertion failure
    """
    text = output.lower()

    if any(
        kw in text for kw in ("connection_timed_out", "network_changed", "net::err_")
    ):
        return "blocked_network"
    if any(kw in text for kw in ("quota", "rate limit", "429")):
        return "blocked_ai_quota"
    if any(kw in text for kw in ("credential", "unauthorized", "401", "forbidden")):
        return "blocked_credentials"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "no tests ran" in text or "no items" in text or "collected 0 items" in text:
        return "no_tests_collected"
    if "syntaxerror" in text:
        return "syntax_error"
    if "modulenotfounderror" in text or "importerror" in text:
        return "import_error"

    return "failed_test"


def write_report(path: Path, attempts: list[dict]) -> None:
    """
    Write a JSON report of all test execution attempts.

    The report includes per-attempt data (status, classification, duration,
    stdout, stderr) and aggregate summary information.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Compute summary
    passed = sum(1 for a in attempts if a["status"] == "passed")
    failed = sum(1 for a in attempts if a["status"] == "failed")

    report = {
        "summary": {
            "total_attempts": len(attempts),
            "passed": passed,
            "failed": failed,
            "final_status": attempts[-1]["status"] if attempts else "unknown",
            "total_duration": sum(a.get("duration", 0) for a in attempts),
        },
        "attempts": attempts,
    }

    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
