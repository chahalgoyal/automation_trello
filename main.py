"""
AI QA Agent — Entry Point

Loads config, creates a timestamped run directory, and dispatches
to run_pipeline() for each enabled test mode (ui / api).

Pipeline steps are implemented in the pipeline/ package:
  pipeline/context.py   — Step 1: context collection
  pipeline/generator.py — Steps 2 & 3: AI suite + code generation
  pipeline/repair.py    — Step 4: execute → repair loop
  pipeline/display.py   — terminal output helpers
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from pipeline._paths import ROOT, RUNS_DIR
from pipeline.context import collect_context
from pipeline.generator import generate_suite_and_code
from pipeline.repair import run_repair_loop

load_dotenv()


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


# -- Core Pipeline ------------------------------------------------------------


def run_pipeline(
    test_type: str,
    config_section: dict,
    max_repairs: int,
    run_dir: Path,
) -> None:
    """Run the complete Generate -> Run -> Repair pipeline for one test mode."""
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

    report_path = report_dir / f"{test_type}_report.json"
    generated_test = test_dir / f"test_{test_type}_case.py"
    suite_path = suite_dir / f"{test_type}_test_suite.md"

    # Step 1 — collect context (snapshot or README)
    snapshot, readme_content = collect_context(test_type, config_section, target_url)

    # Steps 2 & 3 — AI generates suite spec + executable code
    suite_md = generate_suite_and_code(
        test_type,
        target_url,
        snapshot,
        readme_content,
        instructions,
        suite_path,
        generated_test,
    )

    # Step 4 — execute → repair loop
    run_repair_loop(
        test_type,
        max_repairs,
        suite_md,
        snapshot,
        generated_test,
        report_dir,
        report_path,
        suite_path,
        history_dir,
    )


# -- Main Entry Point ---------------------------------------------------------


def main():
    config = load_config()
    max_repairs = config.get("max_repair_attempts", 3)

    if config.get("model"):
        os.environ.setdefault("GEMINI_MODEL", config["model"])

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_run_dir = RUNS_DIR / f"run_{timestamp}"
    current_run_dir.mkdir()

    print(f"[INFO] Created new run directory: {current_run_dir.relative_to(ROOT)}")

    modes_run = 0

    if config.get("ui", {}).get("enabled", False):
        run_pipeline("ui", config["ui"], max_repairs, current_run_dir)
        modes_run += 1

    if config.get("api", {}).get("enabled", False):
        run_pipeline("api", config["api"], max_repairs, current_run_dir)
        modes_run += 1

    if modes_run == 0:
        print("[WARN] No test modes (UI or API) are enabled in config.yaml.")
        print("Please set ui.enabled or api.enabled to true.")
        current_run_dir.rmdir()  # Clean up empty dir


if __name__ == "__main__":
    main()
