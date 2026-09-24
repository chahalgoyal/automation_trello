"""
Repair loop — Step 4 of the pipeline.

Handles:
  - building structured attempt records for the JSON report
  - archiving failing test versions to history/
  - requesting AI repair of failing code
  - the full execute → record → repair → retry loop
"""

import shutil
from pathlib import Path

from ai_engine.client import repair_test_code
from runner.executor import execute_attempt
from runner.validator import classify_failure, write_report

from ._paths import ROOT
from .display import print_attempt_output, print_final


def _build_attempt_record(
    attempt_num: int,
    failure_output: str,
    result,
) -> dict:
    """
    Build a structured attempt record for the JSON report.

    Handles both the result-present and result-absent (exception) cases,
    removing the nested ternaries from the repair loop.
    """
    if result is not None:
        status = result.status
        classification = (
            "passed" if status == "passed" else classify_failure(failure_output)
        )
        return {
            "attempt": attempt_num,
            "status": status,
            "classification": classification,
            "duration": result.duration,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    return {
        "attempt": attempt_num,
        "status": "failed",
        "classification": classify_failure(failure_output),
        "duration": 0,
        "stdout": "",
        "stderr": failure_output,
    }


def do_repair(
    version: int,
    max_repairs: int,
    suite_md: str,
    snapshot: str,
    failure_output: str,
    test_type: str,
    test_file_path: Path,
    history_dir: Path,
) -> None:
    """Archive the failing test to history and request AI repair."""
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{test_type}_test_case_v{version}.py"
    shutil.copy2(test_file_path, history_path)

    print(f"\n  [RETRY] Saved failing version to {history_path.relative_to(ROOT)}")
    print(f"  [RETRY] Requesting AI repair ({version}/{max_repairs})...")

    repaired_code = repair_test_code(
        suite_md,
        snapshot,
        test_file_path.read_text(encoding="utf-8"),
        failure_output,
        test_type,
    )
    test_file_path.write_text(repaired_code, encoding="utf-8")
    print("  [OK] Repaired code written\n")


def run_repair_loop(
    test_type: str,
    max_repairs: int,
    suite_md: str,
    snapshot: str,
    generated_test: Path,
    report_dir: Path,
    report_path: Path,
    suite_path: Path,
    history_dir: Path,
) -> None:
    """Step 4 of the pipeline: execute tests and repair on failure."""
    tag = test_type.upper()
    print(
        f"\n[{tag}] [4/4] Entering test execution loop"
        f" (up to {max_repairs} repairs)...\n"
    )

    attempts = []

    for attempt in range(max_repairs + 1):
        attempt_num = attempt + 1
        print(
            f"{'-' * 20} Attempt {attempt_num}/{max_repairs + 1}" f" ({tag}) {'-' * 20}"
        )

        try:
            failure_output, result = execute_attempt(generated_test, report_dir)
        except (SyntaxError, ValueError) as error:
            failure_output = str(error)
            print(f"  [FAIL] Validation failed: {failure_output}")
            attempts.append(_build_attempt_record(attempt_num, failure_output, None))
            write_report(report_path, attempts)
            if attempt == max_repairs:
                print_final(
                    test_type, max_repairs, suite_path, generated_test, report_path
                )
                return
            do_repair(
                attempt_num,
                max_repairs,
                suite_md,
                snapshot,
                failure_output,
                test_type,
                generated_test,
                history_dir,
            )
            continue

        if result is not None:
            failure_output = result.traceback

        attempts.append(_build_attempt_record(attempt_num, failure_output, result))
        write_report(report_path, attempts)

        if result is not None:
            print_attempt_output(result)
            if result.exit_code == 0:
                print_final(
                    test_type,
                    attempt_num,
                    suite_path,
                    generated_test,
                    report_path,
                    success=True,
                )
                return

        if attempt == max_repairs:
            print_final(test_type, max_repairs, suite_path, generated_test, report_path)
            return

        do_repair(
            attempt_num,
            max_repairs,
            suite_md,
            snapshot,
            failure_output,
            test_type,
            generated_test,
            history_dir,
        )
