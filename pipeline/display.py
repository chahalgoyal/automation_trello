"""
Terminal output helpers for the pipeline.

Keeps all print/banner/display logic in one place so the rest of
the pipeline modules stay focused on their own concerns.
"""

from pathlib import Path

from ._paths import ROOT


def print_attempt_output(result) -> None:
    """Print condensed stdout/stderr from a pytest result."""
    if result.stdout:
        for line in result.stdout.strip().split("\n")[-15:]:
            print(f"  | {line}")
    if result.stderr:
        for line in result.stderr.strip().split("\n")[-10:]:
            print(f"  | {line}")
    print(f"  \\- {result.status.upper()} ({result.duration:.2f}s)")


def print_final(
    test_type: str,
    count: int,
    suite_path: Path,
    generated_test: Path,
    report_path: Path,
    success: bool = False,
) -> None:
    """Print the final status banner for a pipeline mode."""
    icon = "[OK]" if success else "[FAIL]"
    msg = (
        f"ALL {test_type.upper()} TESTS PASSED on attempt {count}"
        if success
        else f"{test_type.upper()} FAILED after {count} repair attempt(s)"
    )
    print(f"\n{'=' * 60}")
    print(f"  {icon} {msg}")
    print(f"  Suite:  {suite_path.relative_to(ROOT)}")
    print(f"  Code:   {generated_test.relative_to(ROOT)}")
    print(f"  Report: {report_path.relative_to(ROOT)}")
    print(f"{'=' * 60}\n")
