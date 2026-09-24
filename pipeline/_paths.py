"""Shared path constants — imported by all pipeline sub-modules."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "generated"
RUNS_DIR = GENERATED_DIR / "runs"
