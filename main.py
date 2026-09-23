"""
AI QA Agent - Orchestrator

The main pipeline: Generate -> Run -> Repair

Flow:
  1. Load config.yaml
  2. Create a unique run folder (e.g. generated/runs/run_YYYYMMDD_HHMMSS/)
  3. For each enabled test mode (ui, api):
     a. Collect inputs (MCP snapshot for UI, README for API)
     b. AI generates a structured test suite .md
     c. AI generates executable pytest code
     d. Retry loop: validate syntax, collect tests, run full tests
     e. If FAIL -> request AI repair and retry
"""

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ai_engine.client import (
    generate_ui_test_suite,
    generate_api_test_suite,
    generate_test_code,
    repair_test_code
)
from browser.mcp_snapshot import get_page_snapshot
from runner.executor import run_pytest
from runner.validator import classify_failure, validate_python, write_report

load_dotenv()

# -- Paths --------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
RUNS_DIR = GENERATED_DIR / "runs"

# -- Config -------------------------------------------------------------------

def load_config() -> dict:
    """Load and validate project configuration from config.yaml."""
    config_path = ROOT / "config.yaml"

    if not config_path.exists():
        print("[FAIL] Error: config.yaml not found.")
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


# -- Repair Helper ------------------------------------------------------------

def _do_repair(
    version: int,
    max_repairs: int,
    suite_md: str,
    snapshot: str,
    failure_output: str,
    test_type: str,
    test_file_path: Path,
    history_dir: Path,
) -> None:
    """Save the failing test to history and request AI repair."""
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


# -- Core Pipeline ------------------------------------------------------------

def run_pipeline(
    test_type: str,
    config_section: dict,
    model_name: str,
    max_repairs: int,
    run_dir: Path
) -> None:
    """Run the complete Generate -> Run -> Repair pipeline for a specific mode."""
    print()
    print("+" + "-" * 58 + "+")
    print(f"|   AI QA Agent - Pipeline: {test_type.upper():<30} |")
    print("+" + "-" * 58 + "+")
    
    target_url = config_section.get("target_url") or config_section.get("base_url")
    instructions = config_section.get("instructions", "")
    
    # Directory structure for this specific run
    suite_dir = run_dir / "suites"
    test_dir = run_dir / "tests"
    history_dir = test_dir / "history"
    report_dir = run_dir / "reports"
    
    suite_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    # Files specific to this mode
    report_path = report_dir / f"{test_type}_report.json"
    generated_test = test_dir / f"test_{test_type}_case.py"
    suite_path = suite_dir / f"{test_type}_test_suite.md"

    # -- Step 1: Collect Context ---------------------------------
    snapshot = ""
    readme_content = ""
    
    if test_type == "ui":
        print(f"\n[{test_type.upper()}] [1/4] Collecting browser snapshot via MCP...")
        try:
            snapshot = get_page_snapshot(target_url)
            print(f"  [OK] Snapshot collected ({len(snapshot)} chars)")
        except Exception as e:
            print(f"  [WARN] Snapshot collection failed: {e}")
            print("  Continuing without snapshot - AI will have less context")
    elif test_type == "api":
        print(f"\n[{test_type.upper()}] [1/4] Collecting API documentation...")
        readme_path_str = config_section.get("readme_path")
        if readme_path_str:
            readme_path = Path(readme_path_str)
            if readme_path.exists():
                readme_content = readme_path.read_text(encoding="utf-8")
                print(f"  [OK] Loaded README ({len(readme_content)} chars)")
            else:
                print(f"  [WARN] README not found at {readme_path}")
        else:
            print("  [WARN] No readme_path configured for API mode")

    # -- Step 2: AI generates test suite .md ------------------------------
    print(f"\n[{test_type.upper()}] [2/4] AI is generating a test suite specification...")
    
    if test_type == "ui":
        suite_md = generate_ui_test_suite(target_url, snapshot, instructions)
    else:
        suite_md = generate_api_test_suite(target_url, readme_content, instructions)

    suite_path.write_text(suite_md, encoding="utf-8")
    print(f"  [OK] Suite specification saved: {suite_path.relative_to(ROOT)}")

    # -- Step 3: AI generates executable test code ------------------------
    print(f"\n[{test_type.upper()}] [3/4] AI is generating executable pytest code...")
    generated_code = generate_test_code(suite_md, snapshot, test_type)

    generated_test.write_text(generated_code, encoding="utf-8")
    print(f"  [OK] Test code saved: {generated_test.relative_to(ROOT)}")

    # -- Step 4: Run -> Repair loop (the USP) ------------------------------
    print(f"\n[{test_type.upper()}] [4/4] Entering test execution loop (up to {max_repairs} repairs)...\n")

    attempts = []

    for attempt in range(max_repairs + 1):
        attempt_num = attempt + 1
        print(f"{'-' * 20} Attempt {attempt_num}/{max_repairs + 1} ({test_type.upper()}) {'-' * 20}")

        # -- 4a. Validate Python syntax -----------------------------------
        try:
            validate_python(generated_test)
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
            write_report(report_path, attempts)

            if attempt == max_repairs:
                _print_final(test_type, "FAILED", max_repairs, suite_path, generated_test, report_path)
                return

            _do_repair(attempt_num, max_repairs, suite_md, snapshot, failure_output, test_type, generated_test, history_dir)
            continue

        # -- 4b. Collect tests (dry run) ----------------------------------
        result = None
        failure_output = ""

        try:
            collection = run_pytest(generated_test, report_dir, collect_only=True)
            if collection.exit_code != 0:
                print("  [FAIL] Test collection failed")
                result = collection
            else:
                print("  [OK] Tests collected successfully")
                # -- 4c. Full test run ------------------------------------
                result = run_pytest(generated_test, report_dir)
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
        write_report(report_path, attempts)

        # -- Print condensed output ---------------------------------------
        if result is not None:
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-15:]:
                    print(f"  | {line}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    print(f"  | {line}")
            print(f"  \\- {result.status.upper()} ({result.duration:.2f}s)")

            # -- Success! -------------------------------------------------
            if result.exit_code == 0:
                _print_final(test_type, "PASSED", attempt_num, suite_path, generated_test, report_path, success=True)
                return

        # -- Max attempts reached -----------------------------------------
        if attempt == max_repairs:
            _print_final(test_type, "FAILED", max_repairs, suite_path, generated_test, report_path)
            return

        # -- Request AI repair --------------------------------------------
        _do_repair(attempt_num, max_repairs, suite_md, snapshot, failure_output, test_type, generated_test, history_dir)


def _print_final(
    test_type: str,
    label: str,
    count: int,
    suite_path: Path,
    generated_test: Path,
    report_path: Path,
    success: bool = False,
) -> None:
    """Print the final status banner."""
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


# -- Main Entry Point ---------------------------------------------------------

def main():
    config = load_config()
    max_repairs = config.get("max_repair_attempts", 3)

    if config.get("model"):
        os.environ.setdefault("GEMINI_MODEL", config["model"])
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    
    # Create a unique directory for this run
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_run_dir = RUNS_DIR / f"run_{timestamp}"
    current_run_dir.mkdir()
    
    print(f"[INFO] Created new run directory: {current_run_dir.relative_to(ROOT)}")
    
    modes_run = 0
    
    if config.get("ui", {}).get("enabled", False):
        run_pipeline("ui", config["ui"], model_name, max_repairs, current_run_dir)
        modes_run += 1
        
    if config.get("api", {}).get("enabled", False):
        run_pipeline("api", config["api"], model_name, max_repairs, current_run_dir)
        modes_run += 1
        
    if modes_run == 0:
        print("[WARN] No test modes (UI or API) are enabled in config.yaml.")
        print("Please set ui.enabled or api.enabled to true.")
        current_run_dir.rmdir()  # Clean up empty dir


if __name__ == "__main__":
    main()
