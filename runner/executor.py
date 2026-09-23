"""
Test execution engine — runs pytest as a subprocess and captures results.

Handles:
- Full test runs with JUnit XML + HTML report generation
- Collection-only runs (to validate test discovery before execution)
- Windows compatibility (cmd.exe wrapper)
- Timeout enforcement (prevents hung tests from blocking the pipeline)
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    """Structured result of a pytest execution."""

    status: str          # "passed" or "failed"
    exit_code: int       # pytest exit code
    duration: float      # wall-clock seconds
    stdout: str          # captured stdout
    stderr: str          # captured stderr
    report_path: str = ""  # path to JUnit XML report (empty for collect-only)

    @property
    def traceback(self) -> str:
        """Return the most useful failure output for AI repair."""
        return self.stderr or self.stdout


def run_pytest(test_file: Path, report_dir: Path, collect_only: bool = False) -> TestResult:
    """
    Execute pytest on the given test file and return structured results.

    Args:
        test_file: Path to the generated test .py file
        report_dir: Path to output test reports
        collect_only: If True, only collect tests without executing them

    Returns:
        TestResult with status, output, and timing information
    """
    test_path = test_file.resolve()

    # Build the pytest command
    command = [sys.executable, "-m", "pytest", str(test_path), "-v"]

    if collect_only:
        command.append("--collect-only")
    else:
        report_dir.mkdir(parents=True, exist_ok=True)
        command.extend([
            "--junitxml", str(report_dir / "test-results.xml"),
            "--html", str(report_dir / "test-report.html"),
            "--self-contained-html",
            "--alluredir", str(report_dir / "allure-results"),
            "--tb=long",  # Full tracebacks for AI repair context
        ])

    # Windows compatibility: wrap in cmd.exe
    if os.name == "nt":
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d", "/s", "/c",
            subprocess.list2cmdline(command),
        ]

    started = time.perf_counter()

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,  # 3-minute timeout per run
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - started
        return TestResult(
            status="failed",
            exit_code=-1,
            duration=duration,
            stdout="",
            stderr="Test execution timed out after 180 seconds",
            report_path="",
        )

    duration = time.perf_counter() - started

    return TestResult(
        status="passed" if completed.returncode == 0 else "failed",
        exit_code=completed.returncode,
        duration=duration,
        stdout=completed.stdout,
        stderr=completed.stderr,
        report_path=str(report_dir / "test-results.xml") if not collect_only else "",
    )
