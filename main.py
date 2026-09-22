"""
AI QA Agent - Orchestrator

The main pipeline: Generate -> Run -> Repair

Flow:
  1. Load config.yaml (target URL, instructions, model, retry count)
  2. Collect browser accessibility snapshot via Playwright MCP (UI mode)
  3. AI generates a structured test suite .md (the key differentiator)
  4. AI generates executable pytest code from the suite + snapshot
  5. Retry loop:
     a. Validate Python syntax
     b. pytest --collect-only (verify test discovery)
     c. pytest full run
     d. If PASS -> done, write report
     e. If FAIL -> save to history, send failure to AI for repair, retry
  6. Write final JSON report
"""

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ai_engine.client import generate_test_code, generate_test_suite, repair_test_code
from browser.mcp_snapshot import get_page_snapshot
from runner.executor import run_pytest
from runner.validator import classify_failure, validate_python, write_report

load_dotenv()

# -- Paths --------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
SUITE_DIR = GENERATED_DIR / "suites"
TEST_DIR = GENERATED_DIR / "tests"
HISTORY_DIR = TEST_DIR / "history"
REPORT_PATH = ROOT / "reports" / "test_report.json"
GENERATED_TEST = TEST_DIR / "test_case.py"


# -- Config -------------------------------------------------------------------


def load_config() -> dict:
    """Load and validate project configuration from config.yaml."""
    config_path = ROOT / "config.yaml"

    if not config_path.exists():
        print("[FAIL] Error: config.yaml not found.")
        print("  Create one with at least 'target_url' and 'instructions'.")
        print("  See config.yaml.example or the README for reference.")
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config.get("target_url"):
        print("[FAIL] Error: 'target_url' must be set in config.yaml")
        sys.exit(1)

    return config


# -- Repair Helper ------------------------------------------------------------


def _do_repair(
    version: int,
    max_repairs: int,
    suite_md: str,
    snapshot: str,
    failure_output: str,
    test_type: str,
) -> None:
    """Save the failing test to history and request AI repair."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_path = HISTORY_DIR / f"test_case_v{version}.py"
    shutil.copy2(GENERATED_TEST, history_path)

    print(f"\n  [RETRY] Saved failing version to {history_path.relative_to(ROOT)}")
    print(f"  [RETRY] Requesting AI repair ({version}/{max_repairs})...")

    repaired_code = repair_test_code(
        suite_md,
        snapshot,
        GENERATED_TEST.read_text(encoding="utf-8"),
        failure_output,
        test_type,
    )
    GENERATED_TEST.write_text(repaired_code, encoding="utf-8")
    print("  [OK] Repaired code written\n")


# -- Main Pipeline ------------------------------------------------------------


def main():
    config = load_config()

    target_url = config["target_url"]
    test_type = config.get("test_type", "ui")
    max_repairs = config.get("max_repair_attempts", 3)
    instructions = config.get(
        "instructions",
        "Generate comprehensive tests for this application.",
    )

    # Set model from config (env var takes precedence if already set)
    if config.get("model"):
        os.environ.setdefault("OLLAMA_MODEL", config["model"])

    # -- Banner -----------------------------------------------------------
    model_name = os.getenv("OLLAMA_MODEL", "gemma4:latest")
    print()
    print("+" + "-" * 58 + "+")
    print("|   AI QA Agent - Generate -> Run -> Repair                |")
    print("+" + "-" * 58 + "+")
    print(f"|  Target:      {target_url:<43}|")
    print(f"|  Mode:        {test_type.upper():<43}|")
    print(f"|  Model:       {model_name:<43}|")
    print(f"|  Max Retries: {str(max_repairs):<43}|")
    print("+" + "-" * 58 + "+")

    # -- Step 1: Collect browser snapshot ---------------------------------
    snapshot = ""
    if test_type == "ui":
        print("\n[1/4] Collecting browser snapshot via MCP...")
        try:
            snapshot = get_page_snapshot(target_url)
            print(f"  [OK] Snapshot collected ({len(snapshot)} chars)")
        except Exception as e:
            print(f"  [WARN] Snapshot collection failed: {e}")
            print("  Continuing without snapshot - AI will have less context")
    else:
        print("\n[1/4] API mode - skipping browser snapshot")

    # -- Step 2: AI generates test suite .md ------------------------------
    print("\n[2/4] AI is generating a test suite specification...")
    suite_md = generate_test_suite(target_url, snapshot, instructions, test_type)

    SUITE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suite_path = SUITE_DIR / f"test_suite_{timestamp}.md"
    suite_path.write_text(suite_md, encoding="utf-8")
    print(f"  [OK] Suite specification saved: {suite_path.relative_to(ROOT)}")

    # -- Step 3: AI generates executable test code ------------------------
    print("\n[3/4] AI is generating executable pytest code...")
    generated_code = generate_test_code(suite_md, snapshot, test_type)

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_TEST.write_text(generated_code, encoding="utf-8")
    print(f"  [OK] Test code saved: {GENERATED_TEST.relative_to(ROOT)}")

    # -- Step 4: Run -> Repair loop (the USP) ------------------------------
    print(f"\n[4/4] Entering test execution loop (up to {max_repairs} repairs)...\n")

    attempts = []

    for attempt in range(max_repairs + 1):
        attempt_num = attempt + 1
        print(f"{'-' * 20} Attempt {attempt_num}/{max_repairs + 1} {'-' * 20}")

        # -- 4a. Validate Python syntax -----------------------------------
        try:
            validate_python(GENERATED_TEST)
            print("  [OK] Python syntax valid")
        except (SyntaxError, ValueError) as error:
            failure_output = str(error)
            print(f"  [FAIL] Validation failed: {failure_output}")

            attempts.append({
                "attempt": attempt_num,
                "status": "failed",
                "classification": classify_failure(failure_output),
                "duration": 0,
                "stdout": "",
                "stderr": failure_output,
            })
            write_report(REPORT_PATH, attempts)

            if attempt == max_repairs:
                _print_final("FAILED", max_repairs, suite_path)
                sys.exit(1)

            _do_repair(attempt_num, max_repairs, suite_md, snapshot, failure_output, test_type)
            continue

        # -- 4b. Collect tests (dry run) ----------------------------------
        result = None
        failure_output = ""

        try:
            collection = run_pytest(GENERATED_TEST, collect_only=True)
            if collection.exit_code != 0:
                print("  [FAIL] Test collection failed")
                result = collection
            else:
                print("  [OK] Tests collected successfully")
                # -- 4c. Full test run ------------------------------------
                result = run_pytest(GENERATED_TEST)
        except Exception as error:
            failure_output = str(error)

        # -- Record attempt -----------------------------------------------
        if result is not None:
            failure_output = result.traceback
            status = result.status
        else:
            status = "failed"

        attempts.append({
            "attempt": attempt_num,
            "status": status,
            "classification": (
                "passed" if status == "passed"
                else classify_failure(failure_output)
            ),
            "duration": result.duration if result else 0,
            "stdout": result.stdout if result else "",
            "stderr": result.stderr if result else failure_output,
        })
        write_report(REPORT_PATH, attempts)

        # -- Print condensed output ---------------------------------------
        if result is not None:
            if result.stdout:
                # Show last 15 lines of stdout (summary area)
                for line in result.stdout.strip().split("\n")[-15:]:
                    print(f"  | {line}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    print(f"  | {line}")
            print(f"  \\- {result.status.upper()} ({result.duration:.2f}s)")

            # -- Success! -------------------------------------------------
            if result.exit_code == 0:
                _print_final("PASSED", attempt_num, suite_path, success=True)
                return

        # -- Max attempts reached -----------------------------------------
        if attempt == max_repairs:
            _print_final("FAILED", max_repairs, suite_path)
            sys.exit(1)

        # -- Request AI repair --------------------------------------------
        _do_repair(attempt_num, max_repairs, suite_md, snapshot, failure_output, test_type)


def _print_final(
    label: str,
    count: int,
    suite_path: Path,
    success: bool = False,
) -> None:
    """Print the final status banner."""
    icon = "[OK]" if success else "[FAIL]"
    msg = (
        f"ALL TESTS PASSED on attempt {count}"
        if success
        else f"FAILED after {count} repair attempt(s)"
    )
    print(f"\n{'=' * 60}")
    print(f"  {icon} {msg}")
    print(f"  Suite:  {suite_path.relative_to(ROOT)}")
    print(f"  Code:   {GENERATED_TEST.relative_to(ROOT)}")
    print(f"  Report: {REPORT_PATH.relative_to(ROOT)}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
